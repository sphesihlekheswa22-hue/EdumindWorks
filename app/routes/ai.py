from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from datetime import datetime
import json
from app.utils.app_time import app_now, app_today
import requests
import re
from app import db
from app.models import (
    ChatSession, ChatMessage, StudyPlan, StudyPlanItem, 
    CourseMaterial, Course, Student, Enrollment, Quiz, QuizQuestion
)
from flask import current_app

ai_bp = Blueprint('ai', __name__, url_prefix='/ai')

AI_MODEL_DEFAULT = "nvidia/nemotron-3-nano-30b-a3b:free"
OLLAMA_BASE_URL_DEFAULT = "http://127.0.0.1:11434"
OLLAMA_MODEL_DEFAULT = "llama3.2"


def _cfg_ollama_base_url() -> str:
    """Ollama HTTP base (from Flask config; see app.config OLLAMA_BASE_URL)."""
    return (current_app.config.get("OLLAMA_BASE_URL") or "").strip()


def _cfg_ollama_model() -> str:
    return (current_app.config.get("OLLAMA_MODEL") or OLLAMA_MODEL_DEFAULT).strip()


def _wants_json_response() -> bool:
    """True when chat send should return JSON (fetch + X-Requested-With)."""
    return (request.headers.get("X-Requested-With") or "").strip().lower() == "xmlhttprequest"


def _openrouter_headers(api_key: str) -> dict:
    """Headers OpenRouter recommends for attribution (rankings / fewer odd failures)."""
    ref = (current_app.config.get("OPENROUTER_REFERER") or "http://127.0.0.1:5000").strip()
    title = (current_app.config.get("OPENROUTER_APP_TITLE") or "EduMind AI").strip()
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Referer": ref,
        "X-Title": title,
    }


def _ai_enabled() -> bool:
    # Enabled if either OpenRouter is configured OR Ollama is configured
    api_key = current_app.config.get("OPENROUTER_API_KEY")
    if api_key and str(api_key).strip():
        return True
    return bool(_cfg_ollama_base_url())


def _ai_provider() -> str:
    """Return active provider: 'ollama' or 'openrouter'.

    If OPENROUTER_API_KEY is set, use OpenRouter first. Otherwise use Ollama when
    OLLAMA_BASE_URL is set. This avoids Render/production hangs when OLLAMA_BASE_URL
    points at localhost on the server (no daemon there).
    """
    api_key = current_app.config.get("OPENROUTER_API_KEY")
    if api_key and str(api_key).strip():
        return "openrouter"
    if _cfg_ollama_base_url():
        return "ollama"
    return "openrouter"


def _ollama_chat(messages: list[dict], model: str, base_url: str, timeout: int = 90) -> str:
    """
    Call Ollama's chat API (`POST /api/chat`).
    Requires Ollama running and the model pulled: `ollama pull <model>`.
    """
    base_url = (base_url or OLLAMA_BASE_URL_DEFAULT).rstrip("/")
    resp = requests.post(
        url=f"{base_url}/api/chat",
        headers={"Content-Type": "application/json"},
        data=json.dumps(
            {
                "model": model,
                "messages": messages,
                "stream": False,
            }
        ),
        timeout=timeout,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Ollama HTTP {resp.status_code}: {resp.text}")
    data = resp.json()
    msg = (data.get("message") or {})
    content = msg.get("content")
    if not content:
        raise RuntimeError(f"Ollama returned unexpected payload: {data}")
    return content


def _fallback_tutor_response(user_message: str, session: ChatSession | None = None) -> str:
    """
    Local, rule-based fallback so the AI pages stay useful even with no API key.
    This avoids 500s and gives the student actionable next steps.
    """
    msg = (user_message or "").strip()
    msg_l = msg.lower()
    topic = (getattr(session, "topic", None) or "your subject").strip()

    def _bullet(items: list[str]) -> str:
        return "\n".join([f"- {i}" for i in items])

    # Very short / empty
    if not msg:
        return (
            "AI is currently running in offline mode.\n\n"
            f"Tell me what you’re working on in **{topic}** and paste the question or problem statement."
        )

    # Math-like prompt
    if re.search(r"[\d][\d\s\+\-\*/\^\(\)=]+", msg) or any(k in msg_l for k in ["solve", "calculate", "equation", "derivative", "integral"]):
        steps = _bullet(
            [
                "Write down what’s given and what you must find.",
                "Choose the relevant formula/rule (and why it applies).",
                "Work through algebra carefully (show each step).",
                "Check units/constraints and verify the final answer.",
                "If you share your attempt, I’ll pinpoint the exact step where it goes wrong.",
            ]
        )
        return (
            "AI is currently in **offline mode** (no external model connected), but I can still help you structure the solution.\n\n"
            "**Step-by-step approach:**\n"
            f"{steps}\n\n"
            f"Send the full problem text (and your attempt) and I’ll guide you through it."
        )

    # “Explain” prompts
    if any(k in msg_l for k in ["explain", "understand", "what is", "why", "difference between"]):
        learn = _bullet(
            [
                "Definition in one sentence (in your own words).",
                "A simple example.",
                "A common mistake/misconception.",
                "A quick self-check question to confirm understanding.",
            ]
        )
        return (
            "AI is currently in **offline mode**, but here’s a strong way to learn this topic fast:\n\n"
            "**How to understand it:**\n"
            f"{learn}\n\n"
            f"Tell me the exact concept in **{topic}** and I’ll write the definition + example + self-check."
        )

    # Study-plan / planning prompts
    if any(k in msg_l for k in ["study plan", "plan", "schedule", "revise", "revision", "exam"]):
        tpl = _bullet(
            [
                "Week 1: Foundations + summary notes (1 page per topic).",
                "Week 2: Practice questions daily (timed).",
                "Week 3: Past papers + fix weak areas.",
                "Week 4: Full mock exams + revision of mistakes.",
            ]
        )
        return (
            "AI is currently in **offline mode**, but you can still build a great plan:\n\n"
            "**A simple 4-week template:**\n"
            f"{tpl}\n\n"
            "If you tell me your exam date + topics list, I’ll map it into a day-by-day schedule."
        )

    # Default helpful response
    return (
        "AI is currently running in **offline mode** (no OpenRouter key configured), but I can still help.\n\n"
        "Send one of these and I’ll respond:\n"
        "- The exact question/problem\n"
        "- Your current notes/attempt\n"
        "- What specifically confuses you\n"
    )


@ai_bp.route('/health')
def ai_health():
    """Health check for AI configuration."""
    api_key = current_app.config.get("OPENROUTER_API_KEY") or ""
    openrouter_enabled = bool(str(api_key).strip())
    masked_key = (str(api_key)[:10] + "...") if openrouter_enabled and len(str(api_key)) > 10 else ("***" if openrouter_enabled else None)
    provider = _ai_provider()
    enabled = openrouter_enabled or provider == "ollama"
    msg = (
        "AI is enabled."
        if enabled
        else "AI is disabled (no OPENROUTER_API_KEY and no OLLAMA_BASE_URL). Fallback mode is active."
    )

    # Do not 500: allow app to run with AI disabled.
    return jsonify(
        {
            "status": "ok",
            "ai_enabled": enabled,
            "provider": provider,
            "ollama_base_url": _cfg_ollama_base_url() if provider == "ollama" else None,
            "model": _cfg_ollama_model() if provider == "ollama" else AI_MODEL_DEFAULT,
            "api_key_configured": openrouter_enabled,
            "api_key_masked": masked_key,
            "message": msg,
        }
    )


@ai_bp.route('/test')
def ai_test():
    """Smoke test OpenRouter or Ollama (whichever provider is active)."""
    provider = _ai_provider()
    if provider == "ollama":
        client = get_ai_client()
        if not client:
            return jsonify({"error": "Ollama not configured"}), 500
        try:
            text = _ollama_chat(
                [{"role": "user", "content": "Say hello in one sentence."}],
                model=client["model"],
                base_url=client["base_url"],
                timeout=60,
            )
            return jsonify({"provider": "ollama", "reply": text})
        except Exception as e:
            return jsonify({"error": str(e), "hint": "Is Ollama running? Try: ollama serve && ollama pull " + client.get("model", "llama3.2")}), 500

    api_key = current_app.config.get('OPENROUTER_API_KEY')
    if not api_key:
        return jsonify({'error': 'API key not configured'}), 500

    try:
        response = requests.post(
            url="https://openrouter.ai/api/v1/chat/completions",
            headers=_openrouter_headers(api_key),
            data=json.dumps({
                "model": "nvidia/nemotron-3-nano-30b-a3b:free",
                "messages": [{"role": "user", "content": "Say hello in one sentence."}],
                "max_tokens": 100,
                "reasoning": {"enabled": False}
            }),
            timeout=45
        )

        return jsonify({
            'status_code': response.status_code,
            'response': response.json()
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def get_ai_client():
    """Get AI client configuration for OpenRouter or Ollama."""
    provider = _ai_provider()
    if provider == "ollama":
        model = _cfg_ollama_model()
        base_url = _cfg_ollama_base_url() or OLLAMA_BASE_URL_DEFAULT
        base_url = base_url.strip()
        if not base_url:
            return None
        current_app.logger.info(f"AI: Using Ollama at {base_url} model={model}")
        return {"provider": "ollama", "base_url": base_url.rstrip("/"), "model": model}

    api_key = current_app.config.get("OPENROUTER_API_KEY")
    if not api_key or not str(api_key).strip():
        current_app.logger.error("AI: OPENROUTER_API_KEY not configured")
        return None
    current_app.logger.info("AI: OpenRouter API client initialized successfully")
    return {"provider": "openrouter", "api_key": api_key, "base_url": "https://openrouter.ai/api/v1", "model": AI_MODEL_DEFAULT}


@ai_bp.route('/chat')
@login_required
def chat():
    """AI Chat tutor main page."""
    if current_user.role != 'student':
        flash('AI tutoring is available for students only.', 'danger')
        return redirect(url_for('main.dashboard'))
    
    student = Student.query.filter_by(user_id=current_user.id).first()
    
    # Get chat sessions
    sessions = ChatSession.query.filter_by(student_id=student.id)\
        .order_by(ChatSession.updated_at.desc()).limit(10).all()
    
    return render_template('ai_chat.html', sessions=sessions, ai_enabled=_ai_enabled())


@ai_bp.route('/chat/new', methods=['POST'])
@login_required
def new_chat():
    """Start a new chat session."""
    if current_user.role != 'student':
        return jsonify({'error': 'Access denied'}), 403
    
    student = Student.query.filter_by(user_id=current_user.id).first()
    
    course_id = request.form.get('course_id')
    topic = request.form.get('topic', 'General')
    
    session = ChatSession(
        student_id=student.id,
        course_id=course_id or None,
        topic=topic,
        title=f"Chat: {topic}"
    )
    
    db.session.add(session)
    db.session.commit()
    
    # Add welcome message
    welcome = ChatMessage(
        session_id=session.id,
        role='assistant',
        content=f"Hello! I'm your AI tutor. How can I help you with {topic} today?"
    )
    db.session.add(welcome)
    db.session.commit()
    
    return redirect(url_for('ai.chat_session', session_id=session.id))


@ai_bp.route('/chat/<int:session_id>')
@login_required
def chat_session(session_id):
    """View a specific chat session."""
    if current_user.role != 'student':
        flash('Access denied.', 'danger')
        return redirect(url_for('main.dashboard'))
    
    student = Student.query.filter_by(user_id=current_user.id).first()
    
    session = ChatSession.query.get_or_404(session_id)
    if session.student_id != student.id:
        flash('Access denied.', 'danger')
        return redirect(url_for('ai.chat'))
    
    messages = ChatMessage.query.filter_by(session_id=session_id)\
        .order_by(ChatMessage.created_at).all()
    
    # Get all sessions for sidebar
    sessions = ChatSession.query.filter_by(student_id=student.id)\
        .order_by(ChatSession.updated_at.desc()).limit(10).all()
    
    # Get enrolled courses for context
    enrollments = Enrollment.query.filter_by(student_id=student.id, status='active').all()
    courses = [e.course for e in enrollments]
    
    return render_template('ai_chat_session.html', session=session, 
                          messages=messages, sessions=sessions, courses=courses, ai_enabled=_ai_enabled())


@ai_bp.route('/chat/<int:session_id>/send', methods=['POST'])
@login_required
def send_message(session_id):
    """Send a message to AI tutor."""
    if current_user.role != 'student':
        return jsonify({'ok': False, 'error': 'Access denied'}), 403

    student = Student.query.filter_by(user_id=current_user.id).first()
    if not student:
        if _wants_json_response():
            return jsonify({'ok': False, 'error': 'No student profile for this account'}), 400
        flash('AI chat requires a student profile.', 'danger')
        return redirect(url_for('main.dashboard'))

    session = ChatSession.query.get_or_404(session_id)
    if session.student_id != student.id:
        return jsonify({'ok': False, 'error': 'Access denied'}), 403

    user_message = request.form.get('message')
    if not user_message:
        return jsonify({'ok': False, 'error': 'No message provided'}), 400

    # Save user message
    user_msg = ChatMessage(
        session_id=session_id,
        role='user',
        content=user_message
    )
    db.session.add(user_msg)
    db.session.flush()

    # Get conversation history (includes user_msg after flush)
    messages = ChatMessage.query.filter_by(session_id=session_id)\
        .order_by(ChatMessage.created_at).all()
    
    # Build context
    context = f"You are an AI tutor for EduMind AI, a university Learning Management System. "
    
    if session.course:
        context += f"The student is currently studying {session.course.name}. "
    
    context += "Provide helpful, educational responses. Explain concepts clearly and provide examples when appropriate."
    
    # Prepare messages for model (DB already includes the new user message after flush)
    openai_messages = [{"role": "system", "content": context}]
    for msg in messages[-10:]:  # Last 10 messages for context
        openai_messages.append({"role": msg.role, "content": msg.content})
    
    # Get AI response
    client = get_ai_client()
    if not client:
        # Fallback response if no API key
        current_app.logger.warning("AI: No client available - API key missing or invalid")
        ai_response = _fallback_tutor_response(user_message, session=session)
    else:
        try:
            if client.get("provider") == "ollama":
                ai_response = _ollama_chat(
                    openai_messages,
                    model=client["model"],
                    base_url=client["base_url"],
                    timeout=90,
                )
            else:
                current_app.logger.info(f"AI: Sending request to OpenRouter API with model {client.get('model')}")
                response = requests.post(
                    url="https://openrouter.ai/api/v1/chat/completions",
                    headers=_openrouter_headers(client["api_key"]),
                    data=json.dumps({
                        "model": client.get("model") or AI_MODEL_DEFAULT,
                        "messages": openai_messages,
                        "max_tokens": 500,
                        "reasoning": {"enabled": False}
                    }),
                    timeout=95
                )
                if response.status_code != 200:
                    current_app.logger.error(f"AI: HTTP error {response.status_code}: {response.text}")
                    ai_response = f"AI service returned error {response.status_code}. Please try again later."
                else:
                    response_data = response.json()
                    if 'error' in response_data:
                        current_app.logger.error(f"AI: API returned error: {response_data['error']}")
                        ai_response = f"AI service error: {response_data['error'].get('message', 'Unknown error')}"
                    elif 'choices' in response_data and len(response_data['choices']) > 0:
                        message = response_data['choices'][0]['message']
                        ai_response = message.get('content') or message.get('reasoning', 'No response generated')
                        if not ai_response or ai_response == 'No response generated':
                            ai_response = "I received your message but couldn't generate a response. Please try again."
                    else:
                        current_app.logger.error(f"AI: Unexpected response format: {response_data}")
                        ai_response = "I apologize, but I received an unexpected response. Please try again."
                    current_app.logger.info("AI: Received response from OpenRouter API successfully")
        except Exception as e:
            current_app.logger.error(f"AI: OpenRouter API error: {str(e)}")
            # Fall back to offline tutor response so user still gets value.
            ai_response = _fallback_tutor_response(user_message, session=session)
    
    # Save AI response
    ai_msg = ChatMessage(
        session_id=session_id,
        role='assistant',
        content=ai_response
    )
    db.session.add(ai_msg)
    
    # Update session
    session.updated_at = app_now()

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("send_message: commit failed")
        if _wants_json_response():
            return jsonify({'ok': False, 'error': 'Could not save your message. Try again.'}), 500
        flash('Could not save your message. Please try again.', 'danger')
        return redirect(url_for('ai.chat_session', session_id=session_id))

    next_url = url_for('ai.chat_session', session_id=session_id)
    if _wants_json_response():
        return jsonify({'ok': True, 'redirect': next_url})
    return redirect(next_url)


@ai_bp.route('/summarize/<int:material_id>')
@login_required
def summarize_material(material_id):
    """Generate AI summary for a material."""
    if current_user.role != 'student':
        flash('Access denied.', 'danger')
        return redirect(url_for('main.dashboard'))
    
    material = CourseMaterial.query.get_or_404(material_id)
    
    # Check enrollment
    student = Student.query.filter_by(user_id=current_user.id).first()
    enrollment = Enrollment.query.filter_by(student_id=student.id, course_id=material.course_id).first()
    if not enrollment or enrollment.status != 'active':
        flash('Access denied.', 'danger')
        return redirect(url_for('courses.index'))
    
    # For now, return a placeholder (would need to read file content)
    flash('Summary feature requires file content extraction. This feature is under development.', 'info')
    return redirect(url_for('materials.list_materials', module_id=material.module_id))


@ai_bp.route('/study-plan/')
@login_required
def study_plans_index():
    """List all study plans for the student."""
    if current_user.role != 'student':
        flash('Access denied.', 'danger')
        return redirect(url_for('main.dashboard'))
    
    student = Student.query.filter_by(user_id=current_user.id).first()
    plans = StudyPlan.query.filter_by(student_id=student.id)\
        .order_by(StudyPlan.created_at.desc()).all()
    
    return render_template('student/study_plans_list.html', plans=plans)


@ai_bp.route('/study-plan/tasks')
@login_required
def study_plan_tasks():
    """View all study tasks across all plans."""
    if current_user.role != 'student':
        flash('Access denied.', 'danger')
        return redirect(url_for('main.dashboard'))
    
    student = Student.query.filter_by(user_id=current_user.id).first()
    plans = StudyPlan.query.filter_by(student_id=student.id).all()
    plan_ids = [p.id for p in plans]
    
    items = StudyPlanItem.query.filter(StudyPlanItem.study_plan_id.in_(plan_ids))\
        .order_by(StudyPlanItem.order).all()
    
    return render_template('student/study_plan_tasks.html', items=items)


@ai_bp.route('/study-plan/schedule')
@login_required
def study_plan_schedule():
    """View study plan tasks in a schedule/calendar view."""
    if current_user.role != 'student':
        flash('Access denied.', 'danger')
        return redirect(url_for('main.dashboard'))
    
    student = Student.query.filter_by(user_id=current_user.id).first()
    plans = StudyPlan.query.filter_by(student_id=student.id).all()
    plan_ids = [p.id for p in plans]
    
    items = StudyPlanItem.query.filter(StudyPlanItem.study_plan_id.in_(plan_ids))\
        .filter(StudyPlanItem.due_date.isnot(None))\
        .order_by(StudyPlanItem.due_date).all()
    
    from collections import defaultdict
    schedule = defaultdict(list)
    for item in items:
        schedule[item.due_date].append(item)
    
    return render_template('student/study_plan_schedule.html', schedule=dict(schedule))


@ai_bp.route('/study-plan/generate', methods=['POST'])
@login_required
def generate_study_plan():
    """Generate AI study plan."""
    if current_user.role != 'student':
        return jsonify({'error': 'Access denied'}), 403
    
    student = Student.query.filter_by(user_id=current_user.id).first()
    
    course_id = request.form.get('course_id')
    duration_weeks = int(request.form.get('duration_weeks', 4))
    
    course = Course.query.get(course_id) if course_id else None
    
    # Get course context
    context = ""
    if course:
        context += f"Course: {course.name}\n"
        context += f"Description: {course.description or 'N/A'}\n"
        
        # Get modules
        modules = course.modules
        if modules:
            context += "Modules:\n"
            for m in modules:
                context += f"- {m.title}: {m.description or 'No description'}\n"
    
    # Create study plan
    plan = StudyPlan(
        student_id=student.id,
        course_id=course_id,
        title=f"Study Plan - {course.name if course else 'General'}",
        description="AI-generated personalized study plan",
        is_ai_generated=True,
        start_date=app_today(),
        end_date=app_today()
    )
    
    db.session.add(plan)
    db.session.commit()
    
    # Generate study plan items using AI or defaults
    client = get_ai_client()
    
    if client and context:
        plan_content: str | None = None
        try:
            prompt = f"""Create a {duration_weeks}-week study plan for the following course.
{context}

Provide a list of study tasks in this format:
Week 1:
- Task 1: [description]
- Task 2: [description]
Week 2:
...

Make it practical and focused on key topics."""
            
            if client.get("provider") == "ollama":
                current_app.logger.info("AI: Generating study plan with Ollama")
                plan_content = _ollama_chat(
                    [{"role": "user", "content": prompt}],
                    model=client["model"],
                    base_url=client["base_url"],
                    timeout=110,
                )
            else:
                current_app.logger.info("AI: Generating study plan with OpenRouter")
                response = requests.post(
                    url="https://openrouter.ai/api/v1/chat/completions",
                    headers=_openrouter_headers(client["api_key"]),
                    data=json.dumps({
                        "model": client.get("model") or AI_MODEL_DEFAULT,
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 1000,
                        "reasoning": {"enabled": False}
                    }),
                    timeout=55
                )
                response_data = response.json()
                if 'choices' in response_data and len(response_data['choices']) > 0:
                    plan_content = response_data['choices'][0]['message']['content']
                else:
                    plan_content = None

            plan_content = plan_content.strip() if isinstance(plan_content, str) else ""

            # Parse and create items
            if plan_content:
                lines = plan_content.split('\n')
                week = 1
                order = 1
                for line in lines:
                    if line.strip() and (line.startswith('-') or line[0].isdigit()):
                        item = StudyPlanItem(
                            study_plan_id=plan.id,
                            title=line.strip(),
                            task_type='general',
                            order=order,
                            priority='medium'
                        )
                        db.session.add(item)
                        order += 1

                        if 'Week' in line:
                            week = int(''.join(filter(str.isdigit, line))) if any(c.isdigit() for c in line) else week
        except Exception as e:
            # Fallback to default items
            pass
    
    # If no items created, add defaults
    if not plan.items:
        default_items = [
            "Review course syllabus and objectives",
            "Complete reading assignments",
            "Practice with exercises",
            "Review and summarize notes",
            "Take practice quizzes"
        ]
        
        for i, title in enumerate(default_items):
            item = StudyPlanItem(
                study_plan_id=plan.id,
                title=title,
                task_type='general',
                order=i+1,
                priority='medium'
            )
            db.session.add(item)
    
    db.session.commit()
    
    flash('Study plan generated!', 'success')
    return redirect(url_for('ai.view_study_plan', plan_id=plan.id))


@ai_bp.route('/study-plan/<int:plan_id>')
@login_required
def view_study_plan(plan_id):
    """View a study plan."""
    if current_user.role != 'student':
        flash('Access denied.', 'danger')
        return redirect(url_for('main.dashboard'))
    
    student = Student.query.filter_by(user_id=current_user.id).first()
    
    plan = StudyPlan.query.get_or_404(plan_id)
    if plan.student_id != student.id:
        flash('Access denied.', 'danger')
        return redirect(url_for('main.dashboard'))
    
    items = StudyPlanItem.query.filter_by(study_plan_id=plan_id)\
        .order_by(StudyPlanItem.order).all()
    
    from datetime import date
    return render_template('student/study_plan.html', plan=plan, items=items, now=date.today())


@ai_bp.route('/study-plan/<int:item_id>/complete', methods=['POST'])
@login_required
def complete_study_item(item_id):
    """Mark a study plan item as complete."""
    if current_user.role != 'student':
        return jsonify({'error': 'Access denied'}), 403
    
    item = StudyPlanItem.query.get_or_404(item_id)
    plan = item.study_plan
    
    student = Student.query.filter_by(user_id=current_user.id).first()
    if plan.student_id != student.id:
        return jsonify({'error': 'Access denied'}), 403
    
    item.status = 'completed'
    item.completed_at = app_now()
    db.session.commit()
    
    flash('Item marked as complete!', 'success')
    return redirect(url_for('ai.view_study_plan', plan_id=plan.id))
