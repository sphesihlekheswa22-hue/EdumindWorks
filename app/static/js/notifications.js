// Notification System with Real-time Polling

class NotificationSystem {
    constructor() {
        this.unreadCount = 0;
        this.lastPollTime = null;
        this.pollingInterval = null;
        this.csrfToken = this.getCsrfToken();
        this.init();
    }

    getCsrfToken() {
        const el = document.querySelector('meta[name="csrf-token"]');
        return el ? el.getAttribute('content') : null;
    }
    
    init() {
        // Only initialize if user is logged in (notification dropdown exists in `base.html`)
        if (document.getElementById('notificationDropdown')) {
            this.loadUnreadCount();
            this.startPolling();
            this.setupEventListeners();
            this.loadNotifications();
        }
    }
    
    setupEventListeners() {
        // Close dropdown when clicking outside
        document.addEventListener('click', (e) => {
            const container = document.getElementById('notificationContainer');
            if (container && !container.contains(e.target)) {
                const dropdown = document.getElementById('notificationDropdown');
                if (dropdown && !dropdown.classList.contains('hidden')) {
                    dropdown.classList.add('hidden');
                }
            }
        });
        
        // Intervention form handling
        const form = document.getElementById('interventionForm');
        if (form) {
            form.dataset.handlerAttached = '1';
            form.addEventListener('submit', (e) => this.handleInterventionSubmit(e));
        }
        
        // Template selector changes
        const templateSelect = document.getElementById('templateSelect');
        if (templateSelect) {
            templateSelect.addEventListener('change', (e) => this.loadTemplate(e.target.value));
        }
        
        // Character count for message textarea
        const messageTextarea = document.getElementById('interventionMessage');
        if (messageTextarea) {
            messageTextarea.addEventListener('input', () => this.updateCharCount());
        }
    }
    
    async loadUnreadCount() {
        try {
            const response = await fetch('/notifications/api/notifications/unread-count');
            if (response.ok) {
                const data = await response.json();
                this.updateBadge(data.count);
            }
        } catch (error) {
            console.error('Failed to load unread count:', error);
        }
    }
    
    updateBadge(count) {
        this.unreadCount = count;
        const badges = [
            document.getElementById('notificationBadgeMobile'),
            document.getElementById('notificationBadgeDesktop')
        ].filter(Boolean);

        badges.forEach(badge => {
            if (count > 0) {
                badge.textContent = count > 99 ? '99+' : count;
                badge.classList.remove('hidden');
            } else {
                badge.classList.add('hidden');
            }
        });

        const dot = document.getElementById('notificationDot');
        const ping = document.getElementById('notificationDotPing');
        if (dot && ping) {
            if (count > 0) {
                dot.classList.remove('hidden');
                ping.classList.remove('hidden');
            } else {
                dot.classList.add('hidden');
                ping.classList.add('hidden');
            }
        }
    }
    
    async loadNotifications() {
        try {
            const response = await fetch('/notifications/api/notifications?per_page=5');
            if (response.ok) {
                const data = await response.json();
                this.renderNotifications(data.notifications);
            }
        } catch (error) {
            console.error('Failed to load notifications:', error);
        }
    }
    
    renderNotifications(notifications) {
        const list = document.getElementById('notificationList');
        if (!list) return;
        
        if (!notifications || notifications.length === 0) {
            list.innerHTML = `
                <div class="p-8 text-center text-slate-500">
                    <i class="bi bi-bell-slash text-3xl mb-2"></i>
                    <p>No new notifications</p>
                </div>
            `;
            return;
        }
        
        list.innerHTML = notifications.map(n => this.createNotificationHTML(n)).join('');
    }
    
    createNotificationHTML(n) {
        const icons = {
            'intervention_received': 'bi-chat-dots-fill text-blue-400',
            'intervention_sent': 'bi-check-circle-fill text-emerald-400',
            'at_risk_alert': 'bi-exclamation-triangle-fill text-red-400',
            'assignment_due': 'bi-clock-fill text-amber-400',
            'grade_posted': 'bi-clipboard-check-fill text-purple-400',
            'enrollment': 'bi-person-plus-fill text-green-400',
            'course_update': 'bi-book-fill text-indigo-400',
            'material_published': 'bi-file-earmark-text-fill text-blue-400',
            'quiz_published': 'bi-clipboard-check-fill text-emerald-400',
            'assignment_posted': 'bi-journal-plus text-purple-400',
            'quiz_submitted': 'bi-check-square-fill text-cyan-400',
            'message_received': 'bi-envelope-fill text-pink-400',
            'cv_reviewed': 'bi-file-earmark-check-fill text-emerald-400'
        };
        
        const bgColors = {
            'urgent': 'bg-red-500/10 border-red-500/20',
            'high': 'bg-amber-500/10 border-amber-500/20',
            'normal': 'bg-white/5 border-white/10',
            'low': 'bg-white/5 border-white/10'
        };
        
        const iconClass = icons[n.type] || 'bi-bell-fill text-slate-400';
        const bgClass = bgColors[n.priority] || bgColors['normal'];
        const unreadClass = !n.is_read ? 'border-l-2 border-l-blue-500' : '';
        
        return `
            <div class="p-4 ${bgClass} ${unreadClass} hover:bg-white/10 transition-colors cursor-pointer border-b border-white/5" 
                 onclick="notificationSystem.handleNotificationClick(${n.id}, '${n.action_url || ''}')">
                <div class="flex gap-3">
                    <div class="mt-1"><i class="bi ${iconClass}"></i></div>
                    <div class="flex-1 min-w-0">
                        <p class="text-sm font-medium text-white truncate">${n.title}</p>
                        <p class="text-xs text-slate-400 line-clamp-2">${n.message}</p>
                        <div class="flex justify-between items-center mt-2">
                            <span class="text-xs text-slate-500">${this.timeAgo(n.created_at)}</span>
                            ${n.action_text ? `<span class="text-xs text-blue-400">${n.action_text} →</span>` : ''}
                        </div>
                    </div>
                    ${!n.is_read ? '<div class="w-2 h-2 bg-blue-500 rounded-full mt-2"></div>' : ''}
                </div>
            </div>
        `;
    }
    
    timeAgo(dateString) {
        if (!dateString) return '';
        const date = new Date(dateString);
        const now = new Date();
        const seconds = Math.floor((now - date) / 1000);
        
        if (seconds < 60) return 'Just now';
        if (seconds < 3600) return `${Math.floor(seconds/60)}m ago`;
        if (seconds < 86400) return `${Math.floor(seconds/3600)}h ago`;
        return `${Math.floor(seconds/86400)}d ago`;
    }
    
    async handleNotificationClick(id, url) {
        // Mark as read
        try {
            await fetch(`/notifications/api/notifications/${id}/read`, {
                method: 'POST',
                headers: this.csrfToken ? {'X-CSRFToken': this.csrfToken} : {}
            });
            this.unreadCount = Math.max(0, this.unreadCount - 1);
            this.updateBadge(this.unreadCount);
        } catch (error) {
            console.error('Failed to mark as read:', error);
        }
        
        // Navigate if URL provided
        if (url && url !== 'None' && url !== '') {
            window.location.href = url;
        }
    }
    
    async markAllAsRead() {
        try {
            await fetch('/notifications/api/notifications/mark-all-read', {
                method: 'POST',
                headers: this.csrfToken ? {'X-CSRFToken': this.csrfToken} : {}
            });
            this.updateBadge(0);
            this.loadNotifications();
        } catch (error) {
            console.error('Failed to mark all as read:', error);
        }
    }
    
    // Polling for real-time updates
    startPolling() {
        this.poll(); // Immediate first poll
        // Poll every 30 seconds
        this.pollingInterval = setInterval(() => this.poll(), 30000);
    }
    
    async poll() {
        try {
            const url = this.lastPollTime 
                ? `/notifications/api/notifications/poll?since=${this.lastPollTime}`
                : '/notifications/api/notifications/poll';
                
            const response = await fetch(url);
            const data = await response.json();
            
            this.lastPollTime = data.timestamp;
            
            if (data.has_new) {
                this.updateBadge(this.unreadCount + data.notifications.length);
                
                // Show toast notification
                if (data.notifications.length > 0) {
                    this.showToast(`You have ${data.notifications.length} new notification(s)`, 'info');
                }
                
                // If dropdown is open, refresh it
                const dropdown = document.getElementById('notificationDropdown');
                if (dropdown && !dropdown.classList.contains('hidden')) {
                    this.loadNotifications();
                }
            }
        } catch (error) {
            console.error('Polling error:', error);
        }
    }
    
    // Intervention handling
    intervene(studentId, studentName, riskLevel, courseId = null) {
        const studentIdInput = document.getElementById('interventionStudentId');
        const studentNameEl = document.getElementById('interventionStudentName');
        const studentAvatarEl = document.getElementById('interventionStudentAvatar');
        const studentRiskEl = document.getElementById('interventionStudentRisk');
        
        if (studentIdInput) studentIdInput.value = studentId;
        if (studentNameEl) studentNameEl.textContent = studentName;
        if (studentAvatarEl) studentAvatarEl.textContent = studentName.charAt(0).toUpperCase();
        if (studentRiskEl) studentRiskEl.textContent = `At-risk: ${riskLevel}`;
        
        // Store course ID if provided
        if (courseId) {
            let courseInput = document.getElementById('interventionCourseId');
            if (!courseInput) {
                courseInput = document.createElement('input');
                courseInput.type = 'hidden';
                courseInput.id = 'interventionCourseId';
                document.getElementById('interventionForm').appendChild(courseInput);
            }
            courseInput.value = courseId;
        }

        this.loadTemplate('encouragement');

        const modal = document.getElementById('interventionModal');
        const content = document.getElementById('interventionModalContent');
        if (modal && content) {
            modal.classList.remove('hidden');
            setTimeout(() => {
                content.classList.remove('scale-95', 'opacity-0');
                content.classList.add('scale-100', 'opacity-100');
            }, 10);
        }
    }
    
    loadTemplate(template) {
        const templates = {
            attendance: "Hi! I've noticed you've missed several classes recently. I'm concerned about your progress and want to make sure you're okay. Is there anything preventing you from attending? Let's chat.",
            performance: "Hi! I wanted to check in about your recent assignment scores. I'm here to help if you're struggling with the material. Would you like to schedule office hours to review the concepts?",
            encouragement: "Hi! I know this course can be challenging, but I believe in your ability to succeed. You've shown great potential, and I want to support you. Keep going!",
            office_hours: "Hi! I'd like to invite you to my office hours this week. It's a great opportunity to ask questions, review material, or just check in. Hope to see you there!",
            custom: ""
        };
        
        const textarea = document.getElementById('interventionMessage');
        if (textarea && templates[template]) {
            textarea.value = templates[template];
            this.updateCharCount();
        }
    }
    
    updateCharCount() {
        const textarea = document.getElementById('interventionMessage');
        const countEl = document.getElementById('charCount');
        if (textarea && countEl) {
            const count = textarea.value.length;
            countEl.textContent = `${count}/500`;
            
            // Show AI suggestion if message is short
            const suggestion = document.getElementById('aiSuggestion');
            if (suggestion) {
                if (count > 0 && count < 50) {
                    suggestion.classList.remove('hidden');
                } else {
                    suggestion.classList.add('hidden');
                }
            }
        }
    }
    
    async handleInterventionSubmit(e) {
        e.preventDefault();
        
        const studentId = document.getElementById('interventionStudentId').value;
        const message = document.getElementById('interventionMessage').value;
        const template = document.getElementById('templateSelect')?.value || 'custom';
        const courseId = document.getElementById('interventionCourseId')?.value;
        
        const btn = document.getElementById('sendInterventionBtn');
        
        if (!message.trim()) {
            this.showToast('Please enter a message', 'error');
            return;
        }
        
        if (!studentId) {
            this.showToast('No student selected', 'error');
            return;
        }
        
        // Loading state
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<i class="bi bi-hourglass-split animate-spin"></i> Sending...';
        }
        
        try {
            const response = await fetch('/notifications/api/interventions/send', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    ...(this.csrfToken ? {'X-CSRFToken': this.csrfToken} : {})
                },
                body: JSON.stringify({
                    student_id: parseInt(studentId),
                    message: message,
                    template: template,
                    course_id: courseId ? parseInt(courseId) : null
                })
            });
            
            const data = await response.json();
            
            if (response.ok) {
                this.showToast('Message sent successfully!', 'success');
                this.closeInterventionModal();
                // Reload page if on analytics page
                if (typeof refreshAnalytics === 'function') {
                    refreshAnalytics();
                } else {
                    window.location.reload();
                }
            } else {
                throw new Error(data.error || 'Failed to send');
            }
        } catch (error) {
            this.showToast(error.message, 'error');
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = '<i class="bi bi-send"></i> <span>Send Message</span>';
            }
        }
    }
    
    closeInterventionModal() {
        const modal = document.getElementById('interventionModal');
        const content = document.getElementById('interventionModalContent');
        if (modal && content) {
            content.classList.remove('scale-100', 'opacity-100');
            content.classList.add('scale-95', 'opacity-0');
            setTimeout(() => modal.classList.add('hidden'), 300);
        }
    }
    
    showToast(message, type = 'success') {
        const colors = {
            success: 'bg-emerald-500/20 border-emerald-500/30 text-emerald-300',
            error: 'bg-red-500/20 border-red-500/30 text-red-300',
            info: 'bg-blue-500/20 border-blue-500/30 text-blue-300'
        };
        
        const toast = document.createElement('div');
        toast.className = `fixed bottom-4 right-4 px-6 py-3 rounded-xl glass-card border ${colors[type]} transform translate-y-full opacity-0 transition-all duration-300 z-50 flex items-center gap-2`;
        toast.innerHTML = `
            <i class="bi ${type === 'success' ? 'bi-check-circle' : type === 'error' ? 'bi-x-circle' : 'bi-info-circle'}"></i>
            <span class="font-medium">${message}</span>
        `;
        
        document.body.appendChild(toast);
        setTimeout(() => toast.classList.remove('translate-y-full', 'opacity-0'), 10);
        setTimeout(() => {
            toast.classList.add('translate-y-full', 'opacity-0');
            setTimeout(() => toast.remove(), 300);
        }, 3000);
    }
    
    toggleNotifications() {
        const dropdown = document.getElementById('notificationDropdown');
        if (dropdown) {
            dropdown.classList.toggle('hidden');
            if (!dropdown.classList.contains('hidden')) {
                this.loadNotifications();
            }
        }
    }
}

// Global functions for onclick handlers
function toggleNotifications() { 
    if (notificationSystem) notificationSystem.toggleNotifications(); 
}

function markAllAsRead() { 
    if (notificationSystem) notificationSystem.markAllAsRead(); 
}

function closeInterventionModal() { 
    if (notificationSystem) notificationSystem.closeInterventionModal(); 
}

function intervene(studentId, name, risk, courseId = null) { 
    // Be resilient if user clicks before DOMContentLoaded init.
    if (!notificationSystem) {
        try { notificationSystem = new NotificationSystem(); } catch (e) { /* ignore */ }
    }
    if (notificationSystem) notificationSystem.intervene(studentId, name, risk, courseId); 
}

// Initialize on page load
let notificationSystem;
document.addEventListener('DOMContentLoaded', function() {
    notificationSystem = new NotificationSystem();
    window.notificationSystem = notificationSystem;
});
