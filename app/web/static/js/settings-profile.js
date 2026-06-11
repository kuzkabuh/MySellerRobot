/*
Версия: 1.1.0
Описание: интерактивное сохранение профиля пользователя MP Control
Дата изменения: 2026-06-11
*/

class ProfileManager {
    constructor() {
        this.saveTimeout = null;
        this.initEventListeners();
    }
    
    initEventListeners() {
        // Profile form changes
        document.addEventListener('input', (e) => {
            if (e.target.name && ['first_name', 'last_name', 'phone', 'email'].includes(e.target.name)) {
                this.debouncedSaveProfile();
            }
        });
        
        // Company lookup form
        const companyForm = document.querySelector('form[action="/web/settings/company/lookup"]');
        if (companyForm) {
            companyForm.addEventListener('submit', (e) => {
                e.preventDefault();
                this.lookupCompany();
            });
        }
        
        // Company save form
        const saveCompanyForm = document.querySelector('form[action="/web/settings/company/save"]');
        if (saveCompanyForm) {
            saveCompanyForm.addEventListener('submit', (e) => {
                e.preventDefault();
                this.saveCompanyProfile();
            });
        }
        
        // Marketplace API key verification
        document.addEventListener('click', (e) => {
            if (e.target.closest('form[action*="verify"]')) {
                e.preventDefault();
                this.verifyApiKey(e.target.closest('form'));
            }
        });
    }
    
    debouncedSaveProfile() {
        if (this.saveTimeout) {
            clearTimeout(this.saveTimeout);
        }
        
        this.saveTimeout = setTimeout(() => {
            this.saveProfile();
        }, 2000);
    }
    
    async saveProfile() {
        const formData = {
            first_name: document.getElementById('first_name')?.value || '',
            last_name: document.getElementById('last_name')?.value || '',
            phone: document.getElementById('phone')?.value || '',
            email: document.getElementById('email')?.value || '',
            company_name: document.querySelector('input[name="company_name"]')?.value || '',
            inn: document.querySelector('input[name="inn"]')?.value || '',
            ogrn: document.querySelector('input[name="ogrn"]')?.value || '',
            timezone: document.getElementById('timezone')?.value || 'Europe/Moscow',
        };
        
        try {
            const response = await fetch('/web/settings/profile', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(formData)
            });
            
            if (response.ok) {
                this.showNotification('Профиль успешно сохранен', 'success');
            } else {
                const error = await response.text();
                this.showNotification(`Ошибка при сохранении: ${error}`, 'error');
            }
        } catch (error) {
            this.showNotification(`Ошибка при сохранении: ${error}`, 'error');
        }
    }
    
    async lookupCompany() {
        const innInput = document.querySelector('input[name="inn"]');
        if (!innInput) return;
        
        const inn = innInput.value.trim();
        if (!inn) {
            this.showNotification('Введите ИНН', 'error');
            return;
        }
        
        try {
            const response = await fetch(`/web/settings/company/lookup?inn=${encodeURIComponent(inn)}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
                body: `inn=${encodeURIComponent(inn)}`
            });
            
            if (response.ok) {
                window.location.reload();
            } else {
                const error = await response.text();
                this.showNotification(`Ошибка при поиске компании: ${error}`, 'error');
            }
        } catch (error) {
            this.showNotification(`Ошибка при поиске компании: ${error}`, 'error');
        }
    }
    
    async saveCompanyProfile() {
        const innInput = document.querySelector('input[name="inn"]');
        if (!innInput) return;
        
        const inn = innInput.value.trim();
        if (!inn) {
            this.showNotification('Нельзя сохранить профиль компании без ИНН', 'error');
            return;
        }
        
        try {
            const response = await fetch('/web/settings/company/save', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
                body: `inn=${encodeURIComponent(inn)}`
            });
            
            if (response.ok) {
                this.showNotification('Данные компании сохранены', 'success');
                setTimeout(() => window.location.reload(), 1500);
            } else {
                const error = await response.text();
                this.showNotification(`Ошибка при сохранении данных компании: ${error}`, 'error');
            }
        } catch (error) {
            this.showNotification(`Ошибка при сохранении данных компании: ${error}`, 'error');
        }
    }
    
    async verifyApiKey(form) {
        const accountId = form.action.match(/\/verify\/(\d+)/)?[1];
        if (!accountId) return;
        
        try {
            const response = await fetch(`/web/settings/marketplaces/${accountId}/verify`, {
                method: 'POST',
            });
            
            if (response.ok) {
                window.location.reload();
            } else {
                const error = await response.text();
                this.showNotification(`Ошибка при проверке API-ключа: ${error}`, 'error');
            }
        } catch (error) {
            this.showNotification(`Ошибка при проверке API-ключа: ${error}`, 'error');
        }
    }
    
    showNotification(message, type = 'success') {
        const container = document.getElementById('save-notification');
        if (!container) return;
        
        const notification = document.createElement('div');
        notification.className = `notification ${type}`;
        notification.textContent = message;
        
        container.innerHTML = '';
        container.appendChild(notification);
        
        requestAnimationFrame(() => {
            notification.classList.add('show');
        });
        
        setTimeout(() => {
            notification.classList.remove('show');
            setTimeout(() => {
                if (container.contains(notification)) {
                    container.innerHTML = '';
                }
            }, 300);
        }, 3000);
    }
    
    validateEmail(email) {
        const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        return emailRegex.test(email);
    }
    
    validatePhone(phone) {
        const phoneRegex = /^\+?[0-9\s\-\(\)]+$/;
        return phoneRegex.test(phone) && phone.length >= 10;
    }
}

// Initialize profile manager when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.profileManager = new ProfileManager();
});

// Helper functions for backward compatibility
function saveProfile() {
    if (window.profileManager) {
        window.profileManager.saveProfile();
    }
}

function openNotifications() {
    window.location.href = '/web/settings?tab=notifications';
}

function openSecurity() {
    window.location.href = '/web/settings?tab=security';
}

function openCompanySettings() {
    window.location.href = '/web/settings?tab=company';
}

function openTariffManagement() {
    window.location.href = '/web/settings?tab=subscription';
}

function openSecuritySettings() {
    window.location.href = '/web/settings?tab=security';
}