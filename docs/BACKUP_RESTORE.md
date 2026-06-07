# Резервные копии и восстановление MP Control

## Где лежат бэкапы

Production-бэкапы хранятся в `/opt/mpcontrol/backups`:

```text
/opt/mpcontrol/backups/
├── daily/
├── weekly/
├── monthly/
├── tmp/
└── restore/
```

Ежедневный скрипт создаёт:

```text
mpcontrol_db_YYYY-MM-DD_HH-MM-SS.sql.gz
mpcontrol_files_YYYY-MM-DD_HH-MM-SS.tar.gz
mpcontrol_full_YYYY-MM-DD_HH-MM-SS.tar.gz
```

Если включено `BACKUP_ENCRYPTION_ENABLED=1`, рядом с незашифрованным именем будет файл
с суффиксом `.gpg`, а исходный архив удаляется. Без `BACKUP_ENCRYPTION_PASSWORD`
зашифрованный бэкап восстановить невозможно.

В production файловый архив может содержать `.env`, поэтому для `BACKUP_INCLUDE_FILES=1`
нужно включить `BACKUP_ENCRYPTION_ENABLED=1`. Отключить это требование можно только явным
`BACKUP_ALLOW_PLAINTEXT_SECRETS=1`, если администратор осознанно принимает риск.

## Проверить список бэкапов

```bash
cd /opt/mpcontrol
ls -lah /opt/mpcontrol/backups/daily
find /opt/mpcontrol/backups/daily -type f -name 'mpcontrol_db_*.sql.gz*' -printf '%TY-%Tm-%Td %TH:%TM %s %p\n' | sort -r | head
```

## Проверить целостность архива

Для обычного `.sql.gz`:

```bash
gzip -t /opt/mpcontrol/backups/daily/mpcontrol_db_YYYY-MM-DD_HH-MM-SS.sql.gz
gunzip -c /opt/mpcontrol/backups/daily/mpcontrol_db_YYYY-MM-DD_HH-MM-SS.sql.gz | head -n 20
```

Для `.gpg` сначала расшифруйте файл в приватную директорию:

```bash
mkdir -p /opt/mpcontrol/backups/restore
chmod 700 /opt/mpcontrol/backups/restore
gpg --batch --decrypt \
  -o /opt/mpcontrol/backups/restore/mpcontrol_db_restore.sql.gz \
  /opt/mpcontrol/backups/daily/mpcontrol_db_YYYY-MM-DD_HH-MM-SS.sql.gz.gpg
gzip -t /opt/mpcontrol/backups/restore/mpcontrol_db_restore.sql.gz
```

## Безопасное восстановление БД

1. Сделайте аварийный бэкап текущего состояния.
2. Остановите приложение и бота.
3. Очистите целевую БД.
4. Восстановите дамп.
5. Примените миграции, если нужно.
6. Запустите сервис и проверьте web/бота.

Команды:

```bash
cd /opt/mpcontrol

bash scripts/backup_daily.sh

docker compose -f docker-compose.prod.yml stop app bot worker

docker compose -f docker-compose.prod.yml exec -T postgres psql \
  -U "$POSTGRES_USER" \
  -d "$POSTGRES_DB" \
  -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"

gunzip -c /opt/mpcontrol/backups/daily/mpcontrol_db_YYYY-MM-DD_HH-MM-SS.sql.gz | \
docker compose -f docker-compose.prod.yml exec -T postgres psql \
  -U "$POSTGRES_USER" \
  -d "$POSTGRES_DB"

docker compose -f docker-compose.prod.yml run --rm app alembic upgrade head
docker compose -f docker-compose.prod.yml start app bot worker
```

## Восстановить файлы проекта

Файловый архив содержит важные файлы проекта: `.env`, `docker-compose.prod.yml`,
`deploy`, `nginx`, `uploads`, `storage`, `runtime`, если они есть.

```bash
cd /opt/mpcontrol
mkdir -p /opt/mpcontrol/backups/restore/files
tar -xzf /opt/mpcontrol/backups/daily/mpcontrol_files_YYYY-MM-DD_HH-MM-SS.tar.gz \
  -C /opt/mpcontrol/backups/restore/files
```

Перед заменой файлов сравните содержимое и права доступа. `.env` содержит секреты,
не выводите его в консоль и не отправляйте в Telegram.

## Установить systemd timer

```bash
sudo cp deploy/systemd/mpcontrol-backup.service /etc/systemd/system/mpcontrol-backup.service
sudo cp deploy/systemd/mpcontrol-backup.timer /etc/systemd/system/mpcontrol-backup.timer

sudo systemctl daemon-reload
sudo systemctl enable --now mpcontrol-backup.timer

systemctl status mpcontrol-backup.timer
systemctl list-timers | grep mpcontrol
```

Ручной запуск:

```bash
sudo systemctl start mpcontrol-backup.service
```

Логи:

```bash
journalctl -u mpcontrol-backup.service -n 200 --no-pager
tail -n 200 /opt/mpcontrol/logs/backup.log
```

## Проверки после восстановления

```bash
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs --tail=200 app
docker compose -f docker-compose.prod.yml logs --tail=200 bot
docker compose -f docker-compose.prod.yml logs --tail=200 worker
```

Проверьте:

- вход в web-кабинет;
- Telegram-бот отвечает на `/start` и меню;
- пользователи, тарифы, промокоды, обращения, данные компаний и маркетплейсы на месте;
- `alembic current` показывает актуальную миграцию.

## Restore-drill без замены production

Минимальная регулярная проверка:

```bash
cd /opt/mpcontrol
mkdir -p /opt/mpcontrol/backups/restore/drill
gunzip -c /opt/mpcontrol/backups/daily/mpcontrol_db_YYYY-MM-DD_HH-MM-SS.sql.gz \
  > /opt/mpcontrol/backups/restore/drill/latest.sql
grep -Eq 'PostgreSQL database dump|CREATE TABLE|COPY ' \
  /opt/mpcontrol/backups/restore/drill/latest.sql
```

Для `.gpg` сначала расшифруйте архив в `/opt/mpcontrol/backups/restore`, затем выполните
проверку `gzip -t` и пробный импорт во временную БД. Не выводите `.env` и расшифрованные
архивы в консоль или внешние чаты.

## Внешнее хранилище

Локальный бэкап полезен, но при полной потере сервера он тоже будет потерян.
Рекомендуется подключить внешнее хранилище через `rclone`, `rsync/scp`, S3 или
Яндекс Object Storage. Для этого уже предусмотрены переменные:

```env
BACKUP_REMOTE_ENABLED=0
BACKUP_REMOTE_TYPE=
BACKUP_REMOTE_PATH=
```

Первый этап хранит бэкапы локально. Интеграцию с внешним хранилищем стоит
включить отдельным production-настроечным шагом.

## TODO

- Раз в неделю выполнять тестовое восстановление в отдельную временную БД.
- Подключить внешнее хранилище, чтобы бэкап переживал потерю сервера.
