import json
from datetime import timedelta
from sqlalchemy import select
from .models import *
from .security import hash_password
from .content import COURSES

def seed(db, demo=True, admin_email=None, admin_password=None):
    if db.scalar(select(School.id).limit(1)): return
    school=School(name='Better Education Demo School' if demo else 'Better Education School')
    db.add(school); db.flush()
    cl=Classroom(school_id=school.id,name='8A'); db.add(cl); db.flush()
    admin=User(name='Администратор',email=admin_email or 'admin@be.demo', password_hash=hash_password(admin_password or 'Demo123!'),role='admin',school_id=school.id)
    db.add(admin)
    if not demo:
        db.commit(); return
    teacher=User(name='Дана Апай',email='teacher@be.demo',password_hash=hash_password('Demo123!'),role='teacher',school_id=school.id)
    student=User(name='Аружан',email='student@be.demo',password_hash=hash_password('Demo123!'),role='student',school_id=school.id,classroom_id=cl.id)
    other=User(name='Әли',email='ali@be.demo',password_hash=hash_password('Demo123!'),role='student',school_id=school.id,classroom_id=cl.id)
    parent=User(name='Ата-ана',email='parent@be.demo',password_hash=hash_password('Demo123!'),role='parent',school_id=school.id)
    db.add_all([teacher,student,other,parent]); db.flush(); db.add(ParentLink(parent_id=parent.id,student_id=student.id))
    for name,desc,color,lessons,quizzes in COURSES:
        co=Course(school_id=school.id,classroom_id=cl.id,teacher_id=teacher.id,name=name,description=desc,color=color)
        db.add(co); db.flush()
        for idx,(title,content) in enumerate(lessons): db.add(Lesson(course_id=co.id,title=title,content=content,order_index=idx))
        for title, questions in quizzes:
            payload=[{'prompt':q[0],'options':q[1],'answer':q[2],'explanation':q[3]} for q in questions]
            db.add(Quiz(course_id=co.id,title=title,questions_json=json.dumps(payload,ensure_ascii=False)))
        db.add(Assignment(course_id=co.id,title=f'Практика: {name}',instructions=f'Напиши своими словами, чему ты научился(-ась) в курсе «{name}», и приведи один пример.',due_at=utcnow()+timedelta(days=7)))
        db.add(Grade(student_id=student.id,course_id=co.id,label='Проверочная работа',score=85 if color=='blue' else 78,max_score=100,feedback='Хорошая база. Продолжай практику!'))
        db.add(Event(school_id=school.id,classroom_id=cl.id,title=name+' — урок',when_at=utcnow()+timedelta(days=1),category='lesson'))
    db.add_all([RewardTransaction(student_id=student.id,currency='coin',amount=180,reason='Стартовый бонус',event_key='welcome'),RewardTransaction(student_id=student.id,currency='star',amount=9,reason='Приветственные звёзды',event_key='welcome-star')])
    db.add(Notification(user_id=student.id,text='Добро пожаловать в Better Education! Начни с первого урока.'))
    other_school=School(name='Separate School'); db.add(other_school); db.flush()
    other_class=Classroom(school_id=other_school.id,name='9B'); db.add(other_class); db.flush()
    db.add(User(school_id=other_school.id,classroom_id=other_class.id,name='Ученик другой школы',email='isolated@be.demo',password_hash=hash_password('Demo123!'),role='student'))
    db.commit()
