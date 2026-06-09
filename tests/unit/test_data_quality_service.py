"""version: 1.0.0
description: Unit tests for data quality recommendation helpers.
updated: 2026-05-15
"""

from app.services.common.data_quality_service import DataQualityMetric, _recommendations


def test_data_quality_recommendations_skip_ok_metrics() -> None:
    recommendations = _recommendations(
        [
            DataQualityMetric("Хорошо", 0, "ok", "Проблем нет."),
            DataQualityMetric("Без себестоимости", 3, "critical", "Заполните себестоимость."),
        ]
    )

    assert recommendations == ["Без себестоимости: Заполните себестоимость."]


def test_data_quality_recommendations_return_positive_message_when_clean() -> None:
    recommendations = _recommendations([DataQualityMetric("Хорошо", 0, "ok", "Проблем нет.")])

    assert recommendations == ["Критичных проблем с качеством данных не найдено."]
