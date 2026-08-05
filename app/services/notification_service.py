from app.models.notification import Notification, InterventionMessage, NotificationType, NotificationPriority
from app.models import User, Student, Lecturer, Course
from app.services.risk_service import compute_student_metrics
from app import db
from flask import url_for


class NotificationService:
    """Central service for creating and managing notifications"""
    
    @staticmethod
    def notify_student_intervention(lecturer, student, course, message_content, template='custom'):
        """
        Send intervention message from lecturer to at-risk student
        Creates both the intervention record and notification
        """
        # Create intervention record
        risk_level = 'medium'
        metrics = compute_student_metrics(student.id, course_id=course.id if course else None)
        if metrics.get('has_data'):
            risk_level = metrics['risk_level']
        elif hasattr(student, 'risk_scores') and student.risk_scores:
            latest_risk = student.risk_scores[-1]
            if latest_risk and latest_risk.risk_level:
                risk_level = latest_risk.risk_level
        
        intervention = InterventionMessage(
            lecturer_id=lecturer.id,
            student_id=student.id,
            course_id=course.id if course else None,
            subject=f"Support from {lecturer.user.full_name}",
            content=message_content,
            template_used=template,
            risk_level_at_send=risk_level
        )
        db.session.add(intervention)
        db.session.flush()

        # Create notification for student
        notif = student.user.add_notification(
            type=NotificationType.INTERVENTION_RECEIVED.value,
            title=f"📬 Message from {lecturer.user.full_name}",
            message=message_content[:100] + "..." if len(message_content) > 100 else message_content,
            priority=NotificationPriority.HIGH.value,
            sender=lecturer.user,
            action_url=url_for('notifications.intervention_detail', intervention_id=intervention.id),
            action_text="View Message",
            entity_type='intervention',
            entity_id=intervention.id,
            metadata={
                'lecturer_name': lecturer.user.full_name,
                'course_name': course.name if course else None,
                'template': template
            }
        )
        
        # Notify lecturer that message was sent
        confirm_notif = lecturer.user.add_notification(
            type=NotificationType.INTERVENTION_SENT.value,
            title=f"✅ Message sent to {student.user.full_name}",
            message=f"Your support message has been delivered.",
            priority=NotificationPriority.NORMAL.value,
            action_url=url_for('notifications.interventions_sent'),
            action_text="View Sent Messages"
        )
        
        db.session.commit()
        return intervention, notif
    
    @staticmethod
    def notify_at_risk_alert(lecturer, student, course, performance_score):
        """Alert lecturer about a student flagged at risk (lower performance score = higher concern)."""
        urgent = performance_score is not None and performance_score < 50
        notif = lecturer.user.add_notification(
            type=NotificationType.AT_RISK_ALERT.value,
            title=f"⚠️ At-Risk Student Alert",
            message=(
                f"{student.user.full_name} in {course.code} needs attention "
                f"(Overall performance: {performance_score:.0f}%)"
            ),
            priority=NotificationPriority.URGENT.value if urgent else NotificationPriority.HIGH.value,
            action_url=url_for('analytics.lecturer_analytics'),
            action_text="Review Student",
            entity_type='student',
            entity_id=student.id,
            metadata={'performance_score': performance_score, 'course_id': course.id}
        )
        db.session.commit()
        return notif
    
    @staticmethod
    def notify_grade_posted(student, course, assignment_title, score, max_score):
        """Notify student when grade is posted"""
        notif = student.user.add_notification(
            type=NotificationType.GRADE_POSTED.value,
            title=f"📊 Grade Posted: {assignment_title}",
            message=f"You scored {score}/{max_score} ({int(score/max_score*100)}%) in {course.code}",
            priority=NotificationPriority.NORMAL.value,
            action_url=url_for('marks.course_marks', course_id=course.id),
            action_text="View Marks",
            entity_type='grade',
            entity_id=course.id,
            metadata={'score': score, 'max_score': max_score, 'course_id': course.id}
        )
        db.session.commit()
        return notif
    
    @staticmethod
    def notify_enrollment(student, course):
        """Notify student of successful enrollment"""
        notif = student.user.add_notification(
            type=NotificationType.ENROLLMENT.value,
            title=f"🎉 Enrolled in {course.code}",
            message=f"You have successfully enrolled in {course.name}",
            priority=NotificationPriority.NORMAL.value,
            action_url=url_for('courses.course_detail', course_id=course.id),
            action_text="View Course",
            entity_type='course',
            entity_id=course.id
        )
        db.session.commit()
        return notif
    
    @staticmethod
    def notify_course_update(course, students, message):
        """Notify all students in a course about an update"""
        notifications = []
        for student in students:
            notif = student.user.add_notification(
                type=NotificationType.COURSE_UPDATE.value,
                title=f"📚 Course Update: {course.code}",
                message=message,
                priority=NotificationPriority.NORMAL.value,
                action_url=url_for('courses.course_detail', course_id=course.id),
                action_text="View Course",
                entity_type='course',
                entity_id=course.id
            )
            notifications.append(notif)
        db.session.commit()
        return notifications

    @staticmethod
    def notify_material_published(lecturer, course, module, material, students):
        """Notify students when a new material is published."""
        notifications = []
        action_url = f"/materials/module/{module.id}"
        for student in students:
            notif = student.user.add_notification(
                type=NotificationType.MATERIAL_PUBLISHED.value,
                title=f"📄 New material: {course.code}",
                message=f"{material.title}",
                priority=NotificationPriority.NORMAL.value,
                sender=lecturer.user if lecturer else None,
                action_url=action_url,
                action_text="Open materials",
                entity_type='material',
                entity_id=material.id,
                metadata={'course_id': course.id, 'module_id': module.id}
            )
            notifications.append(notif)
        db.session.commit()
        return notifications

    @staticmethod
    def notify_quiz_published(lecturer, course, module, quiz, students):
        """Notify students when a quiz is published."""
        notifications = []
        action_url = f"/quizzes/module/{module.id}"
        for student in students:
            notif = student.user.add_notification(
                type=NotificationType.QUIZ_PUBLISHED.value,
                title=f"🧩 New quiz published: {course.code}",
                message=f"{quiz.title}",
                priority=NotificationPriority.HIGH.value,
                sender=lecturer.user if lecturer else None,
                action_url=action_url,
                action_text="Open quizzes",
                entity_type='quiz',
                entity_id=quiz.id,
                metadata={'course_id': course.id, 'module_id': module.id}
            )
            notifications.append(notif)
        db.session.commit()
        return notifications

    @staticmethod
    def notify_assignment_posted(lecturer, course, module, assignment, students):
        """Notify students when a new assignment is posted."""
        notifications = []
        action_url = f"/assignments/module/{module.id}"
        for student in students:
            notif = student.user.add_notification(
                type=NotificationType.ASSIGNMENT_POSTED.value,
                title=f"📝 New assignment: {course.code}",
                message=f"{assignment.title}",
                priority=NotificationPriority.HIGH.value,
                sender=lecturer.user if lecturer else None,
                action_url=action_url,
                action_text="Open assignments",
                entity_type='assignment',
                entity_id=assignment.id,
                metadata={'course_id': course.id, 'module_id': module.id}
            )
            notifications.append(notif)
        db.session.commit()
        return notifications
    
    @staticmethod
    def notify_quiz_submitted(lecturer, student, course, quiz_title):
        """Notify lecturer when a student submits a quiz"""
        notif = lecturer.user.add_notification(
            type=NotificationType.QUIZ_SUBMITTED.value,
            title=f"📝 Quiz Submitted",
            message=f"{student.user.full_name} submitted {quiz_title} in {course.code}",
            priority=NotificationPriority.NORMAL.value,
            action_url=url_for('quizzes.list_quizzes', course_id=course.id),
            action_text="View Quizzes",
            entity_type='quiz',
            entity_id=course.id,
            metadata={'student_name': student.user.full_name, 'quiz_title': quiz_title}
        )
        db.session.commit()
        return notif
    
    @staticmethod
    def mark_all_as_read(user):
        """Mark all notifications as read for user"""
        Notification.query.filter_by(recipient_id=user.id, is_read=False).update({
            'is_read': True,
            'read_at': db.func.now()
        })
        user.last_notification_read = db.func.now()
        db.session.commit()
    
    @staticmethod
    def get_unread_count(user):
        """Get unread notification count"""
        return Notification.query.filter_by(recipient_id=user.id, is_read=False).count()
    
    @staticmethod
    def get_notifications(user, page=1, per_page=20, unread_only=False):
        """Get paginated notifications for user"""
        query = Notification.query.filter_by(recipient_id=user.id)
        
        if unread_only:
            query = query.filter_by(is_read=False)
        
        return query.order_by(Notification.created_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
    
    @staticmethod
    def get_interventions_sent(lecturer, page=1, per_page=20):
        """Get interventions sent by lecturer"""
        return InterventionMessage.query.filter_by(lecturer_id=lecturer.id)\
            .order_by(InterventionMessage.sent_at.desc())\
            .paginate(page=page, per_page=per_page, error_out=False)
    
    @staticmethod
    def get_interventions_received(student, page=1, per_page=20):
        """Get interventions received by student"""
        return InterventionMessage.query.filter_by(student_id=student.id)\
            .order_by(InterventionMessage.sent_at.desc())\
            .paginate(page=page, per_page=per_page, error_out=False)
    
    @staticmethod
    def mark_intervention_opened(intervention_id, student_id):
        """Mark an intervention as opened by student"""
        intervention = InterventionMessage.query.filter_by(
            id=intervention_id, student_id=student_id
        ).first()
        if intervention and not intervention.opened_at:
            intervention.opened_at = db.func.now()
            db.session.commit()
        return intervention
    
    @staticmethod
    def reply_to_intervention(intervention_id, student_id, reply_content):
        """Student replies to an intervention message"""
        intervention = InterventionMessage.query.filter_by(
            id=intervention_id, student_id=student_id
        ).first()
        
        if intervention:
            intervention.student_replied = True
            db.session.commit()
            
            # Notify lecturer of reply
            notif = intervention.lecturer.user.add_notification(
                type=NotificationType.MESSAGE_RECEIVED.value,
                title=f"💬 Reply from {intervention.student.user.full_name}",
                message=reply_content[:100] + "..." if len(reply_content) > 100 else reply_content,
                priority=NotificationPriority.NORMAL.value,
                action_url=url_for('notifications.intervention_detail', intervention_id=intervention.id),
                action_text="View Reply",
                entity_type='intervention',
                entity_id=intervention.id
            )
            db.session.commit()
            return intervention, notif
        return None, None
