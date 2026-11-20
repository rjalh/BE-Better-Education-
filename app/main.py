import json, os, secrets, time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool
from .models import *
from .security import hash_password, check_password, make_token, read_token
from .content import REWARDS, HELP_LIBRARY
from .seed import seed

ROOT=Path(__file__).resolve().parent
STATIC=ROOT/'static'

class LoginIn(BaseModel):
    email: str
    password: str
class QuizSubmit(BaseModel):
    answers: list[int | None] = Field(max_length=100)
class TextInput(BaseModel):
    content: str = Field(min_length=3,max_length=15000)
class GradeInput(BaseModel):
    student_id: int
    course_id: int
    label: str = Field(min_length=2,max_length=160)
    score: float = Field(ge=0)
    max_score: float = Field(gt=0,le=10000)
    feedback: str = Field(default='',max_length=3000)
class AssignmentInput(BaseModel):
    course_id: int
    title: str = Field(min_length=3,max_length=160)
    instructions: str = Field(min_length=5,max_length=5000)
    due_at: datetime
class EventInput(BaseModel):
    classroom_id: int
    title: str = Field(min_length=3,max_length=160)
    when_at: datetime
    category: str = 'lesson'
class ReviewInput(BaseModel):
    score: float = Field(ge=0,le=100)
    feedback: str = Field(min_length=2,max_length=2000)
class ProfileInput(BaseModel):
    name: str | None = Field(default=None,min_length=2,max_length=120)
    locale: Literal['ru','kk','en'] | None = None
    theme: str | None = None
class AssistantInput(BaseModel):
    message: str = Field(min_length=2,max_length=1000)
class UserInput(BaseModel):
    name: str = Field(min_length=2,max_length=120)
    email: str = Field(min_length=5,max_length=180)
    password: str = Field(min_length=10,max_length=128)
    role: Literal['student','teacher','parent']
    classroom_id: int | None = None
class ClassroomInput(BaseModel):
    name: str = Field(min_length=2,max_length=70)
class CourseInput(BaseModel):
    classroom_id: int
    teacher_id: int
    name: str = Field(min_length=2,max_length=100)
    description: str = Field(default='',max_length=240)
    color: Literal['blue','violet','mint','peach','gold'] = 'blue'
class LessonInput(BaseModel):
    course_id: int
    title: str = Field(min_length=3,max_length=150)
    content: str = Field(min_length=10,max_length=12000)
class QuestionInput(BaseModel):
    prompt: str = Field(min_length=4,max_length=500)
    options: list[str] = Field(min_length=4,max_length=4)
    answer: int = Field(ge=0,le=3)
    explanation: str = Field(min_length=3,max_length=2000)
class QuizInput(BaseModel):
    course_id: int
    title: str = Field(min_length=4,max_length=160)
    questions: list[QuestionInput] = Field(min_length=1,max_length=30)
class PasswordInput(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10,max_length=128)
class SchoolInput(BaseModel):
    name: str = Field(min_length=3,max_length=150)
class AnnouncementInput(BaseModel):
    course_id: int
    text: str = Field(min_length=5,max_length=250)
class ParentLinkInput(BaseModel):
    parent_id: int
    student_id: int


def fail(code=403,message='Недостаточно прав'):
    raise HTTPException(status_code=code,detail=message)
def timestamp(x): return x.isoformat(timespec='minutes') if x else None

def make_app(database_url=None, demo=None):
    dburl=database_url or os.getenv('DATABASE_URL') or 'sqlite:///'+str(ROOT.parent/'data'/'better.db')
    if dburl.startswith('sqlite:///') and ':memory:' not in dburl:
        Path(dburl.removeprefix('sqlite:///')).parent.mkdir(parents=True,exist_ok=True)
    connect_args={'check_same_thread':False,'timeout':30} if dburl.startswith('sqlite') else {}
    engine=create_engine(dburl,connect_args=connect_args,poolclass=StaticPool if dburl.endswith(':memory:') else None)
    SessionLocal=sessionmaker(bind=engine,autoflush=False,expire_on_commit=False)
    demo = (os.getenv('BE_DEMO_MODE','1')=='1') if demo is None else demo
    secret=os.getenv('SESSION_SECRET') or (secrets.token_urlsafe(48) if demo else None)
    if not secret: raise RuntimeError('Set SESSION_SECRET before production startup')
    if not demo and (not os.getenv('ADMIN_EMAIL') or not os.getenv('ADMIN_PASSWORD')):
        raise RuntimeError('Set ADMIN_EMAIL and ADMIN_PASSWORD for initial account')
    secure=os.getenv('COOKIE_SECURE','0')=='1'
    failed_logins={}

    @asynccontextmanager
    async def lifespan(app):
        Base.metadata.create_all(bind=engine)
        with SessionLocal() as db:
            seed(db,demo=demo,admin_email=os.getenv('ADMIN_EMAIL'),admin_password=os.getenv('ADMIN_PASSWORD'))
        yield
        engine.dispose()
    app=FastAPI(title='Better Education API',version='1.0.0',lifespan=lifespan, docs_url='/docs' if demo else None, redoc_url=None)
    app.state.Session=SessionLocal
    app.state.secret=secret
    app.mount('/static',StaticFiles(directory=STATIC),name='static')

    @app.middleware('http')
    async def origin_guard(request:Request,call_next):
        if request.url.path.startswith('/api/') and request.method not in ('GET','HEAD','OPTIONS'):
            origin=request.headers.get('origin')
            if origin:
                host=request.headers.get('host','')
                from urllib.parse import urlparse
                if urlparse(origin).netloc != host:
                    return Response(status_code=403,content='Origin not permitted')
            # Custom header cannot be supplied by ordinary cross-origin HTML forms.
            if request.headers.get('x-be-request') != '1':
                return Response(status_code=403,content='Missing request token')
        return await call_next(request)

    def get_db():
        with SessionLocal() as db: yield db
    def current_user(request:Request,db:Session=Depends(get_db)):
        uid=read_token(secret,request.cookies.get('be_session'))
        user=db.get(User,uid) if uid else None
        if not user: fail(401,'Войдите в аккаунт')
        return user
    def require(user, *roles):
        if user.role not in roles: fail()
    def course_access(db, user, course_id, write=False):
        co=db.get(Course,course_id)
        if not co or co.school_id!=user.school_id: fail(404,'Курс не найден')
        if user.role=='student' and (write or co.classroom_id!=user.classroom_id): fail(403,'Нет доступа к курсу')
        if user.role=='teacher' and co.teacher_id!=user.id: fail()
        if user.role=='parent': fail()
        return co
    def authorized_student(db,user,student_id):
        st=db.get(User,student_id)
        if not st or st.role!='student' or st.school_id!=user.school_id: fail(404,'Ученик не найден')
        if user.role=='student' and st.id!=user.id: fail()
        if user.role=='teacher':
            own_class_ids=db.scalars(select(Course.classroom_id).where(Course.teacher_id==user.id,Course.school_id==user.school_id)).all()
            if st.classroom_id not in own_class_ids: fail()
        if user.role=='parent' and not db.scalar(select(ParentLink.id).where(ParentLink.parent_id==user.id,ParentLink.student_id==st.id)): fail()
        return st
    def award(db,student_id,currency,amount,reason,key):
        if db.scalar(select(RewardTransaction.id).where(RewardTransaction.student_id==student_id,RewardTransaction.event_key==key)):
            return False
        db.add(RewardTransaction(student_id=student_id,currency=currency,amount=amount,reason=reason,event_key=key))
        return True
    def balance(db,student_id,currency):
        return int(db.scalar(select(func.coalesce(func.sum(RewardTransaction.amount),0)).where(RewardTransaction.student_id==student_id,RewardTransaction.currency==currency)) or 0)
    def course_dict(db,co,student_id=None):
        lessons=db.scalars(select(Lesson).where(Lesson.course_id==co.id).order_by(Lesson.order_index)).all()
        quizzes=db.scalars(select(Quiz).where(Quiz.course_id==co.id)).all()
        completed=0
        if student_id:
            lesson_ids=[x.id for x in lessons]
            if lesson_ids: completed=db.scalar(select(func.count()).select_from(LessonProgress).where(LessonProgress.student_id==student_id,LessonProgress.lesson_id.in_(lesson_ids))) or 0
        return {'id':co.id,'name':co.name,'description':co.description,'color':co.color,'lesson_count':len(lessons),'completed':completed,'quiz_count':len(quizzes),'progress':round(completed/len(lessons)*100) if lessons else 0}
    def grade_dict(db,g):
        co=db.get(Course,g.course_id)
        return {'id':g.id,'student_id':g.student_id,'course_id':g.course_id,'course':co.name if co else '—','label':g.label,'score':g.score,'max_score':g.max_score,'percent':round(g.score/g.max_score*100),'feedback':g.feedback,'date':timestamp(g.created_at)}
    def student_overview(db,student_id):
        st=db.get(User,student_id)
        courses=db.scalars(select(Course).where(Course.school_id==st.school_id,Course.classroom_id==st.classroom_id)).all()
        grades=db.scalars(select(Grade).where(Grade.student_id==student_id).order_by(Grade.created_at.desc()).limit(10)).all()
        all_grades=db.scalars(select(Grade).where(Grade.student_id==student_id)).all()
        attempts=db.scalars(select(QuizAttempt).where(QuizAttempt.student_id==student_id).order_by(QuizAttempt.created_at.desc())).all()
        avg=round(sum(g.score/g.max_score*100 for g in all_grades)/len(all_grades)) if all_grades else None
        events=db.scalars(select(Event).where(Event.school_id==st.school_id,Event.classroom_id==st.classroom_id).order_by(Event.when_at).limit(7)).all()
        progress=[{'label': a.created_at.strftime('%d.%m'),'score':round(a.score/a.total*100)} for a in attempts[:8]][::-1]
        return {'name':st.name,'average':avg,'grades':[grade_dict(db,g) for g in grades[:5]], 'courses':[course_dict(db,c,student_id) for c in courses], 'attempt_count':len(attempts),'progress':progress,'balance':{'coin':balance(db,student_id,'coin'),'star':balance(db,student_id,'star')},'events':[{'id':e.id,'title':e.title,'when_at':timestamp(e.when_at),'category':e.category} for e in events], 'completed_lessons':db.scalar(select(func.count()).select_from(LessonProgress).where(LessonProgress.student_id==student_id)) or 0}
    def assignment_dict(db,a,student_id=None):
        co=db.get(Course,a.course_id)
        sub=db.scalar(select(Submission).where(Submission.assignment_id==a.id,Submission.student_id==student_id)) if student_id else None
        return {'id':a.id,'course_id':a.course_id,'course':co.name if co else '', 'title':a.title,'instructions':a.instructions,'due_at':timestamp(a.due_at),'submission':{'id':sub.id,'content':sub.content,'status':sub.status,'score':sub.score,'feedback':sub.feedback} if sub else None}
    def quiz_dict(db,q,student_id=None,include_questions=False):
        co=db.get(Course,q.course_id)
        questions=json.loads(q.questions_json)
        attempts=db.scalars(select(QuizAttempt).where(QuizAttempt.quiz_id==q.id,QuizAttempt.student_id==student_id).order_by(QuizAttempt.created_at.desc())).all() if student_id else []
        d={'id':q.id,'title':q.title,'course_id':q.course_id,'course':co.name,'question_count':len(questions),'attempts':len(attempts),'best':max((round(x.score/x.total*100) for x in attempts),default=None)}
        if include_questions: d['questions']=[{'prompt':x['prompt'],'options':x['options']} for x in questions]
        return d

    @app.get('/health')
    def health(): return {'status':'ok','application':'Better Education','mode':'demo' if demo else 'configured'}
    @app.get('/')
    def home(): return FileResponse(STATIC/'index.html')
    @app.post('/api/login')
    def login(data:LoginIn,response:Response,db:Session=Depends(get_db)):
        email=data.email.strip().lower()
        identifier=email  # Per-email dev rate limit; production should use a shared store/gateway.
        failed=[t for t in failed_logins.get(identifier,[]) if time.monotonic()-t<900]
        if len(failed)>=7: fail(429,'Слишком много попыток. Повтори позже')
        user=db.scalar(select(User).where(User.email==email))
        if not user or not check_password(data.password,user.password_hash):
            failed.append(time.monotonic());failed_logins[identifier]=failed
            fail(401,'Неверная почта или пароль')
        failed_logins.pop(identifier,None)
        response.set_cookie('be_session',make_token(secret,user.id),max_age=604800,httponly=True,samesite='lax',secure=secure,path='/')
        return {'ok':True,'role':user.role}
    @app.post('/api/logout')
    def logout(response:Response):
        response.delete_cookie('be_session',path='/')
        return {'ok':True}
    @app.get('/api/me')
    def me(user:User=Depends(current_user),db:Session=Depends(get_db)):
        school=db.get(School,user.school_id)
        return {'id':user.id,'name':user.name,'email':user.email,'role':user.role,'school':school.name,'school_id':user.school_id,'classroom_id':user.classroom_id,'theme':user.theme,'locale':user.locale,'demo':demo}
    @app.patch('/api/me')
    def update_me(data:ProfileInput,user:User=Depends(current_user),db:Session=Depends(get_db)):
        if data.name is not None: user.name=data.name.strip()
        if data.locale: user.locale=data.locale
        if data.theme is not None:
            themes=['sky']
            if user.role=='student':
                bought=db.scalars(select(Redemption).where(Redemption.student_id==user.id)).all()
                themes.extend(r['theme'] for r in REWARDS if any(b.item_code==r['code'] for b in bought))
            if data.theme not in themes: fail(403,'Тема не приобретена')
            user.theme=data.theme
        db.commit()
        return {'ok':True,'name':user.name,'theme':user.theme,'locale':user.locale}
    @app.get('/api/overview')
    def overview(user:User=Depends(current_user),db:Session=Depends(get_db)):
        if user.role=='student': return student_overview(db,user.id)
        if user.role=='parent':
            ids=db.scalars(select(ParentLink.student_id).where(ParentLink.parent_id==user.id)).all()
            return {'children':[{'id':i,'name':db.get(User,i).name,'overview':student_overview(db,i)} for i in ids]}
        if user.role in ('teacher','admin'):
            courses=db.scalars(select(Course).where(Course.school_id==user.school_id,*([Course.teacher_id==user.id] if user.role=='teacher' else []))).all()
            classids=list(set(c.classroom_id for c in courses))
            students=db.scalars(select(User).where(User.school_id==user.school_id,User.role=='student',User.classroom_id.in_(classids))).all() if classids else []
            submissions=db.scalars(select(Submission).join(Assignment,Submission.assignment_id==Assignment.id).join(Course,Assignment.course_id==Course.id).where(Course.school_id==user.school_id,*([Course.teacher_id==user.id] if user.role=='teacher' else []),Submission.status=='submitted')).all()
            return {'courses':[course_dict(db,c) for c in courses],'students':[{'id':s.id,'name':s.name,'classroom_id':s.classroom_id} for s in students],'pending_submissions':len(submissions),'school':db.get(School,user.school_id).name}
    @app.get('/api/courses')
    def courses(user:User=Depends(current_user),db:Session=Depends(get_db)):
        if user.role=='parent': fail()
        q=select(Course).where(Course.school_id==user.school_id)
        if user.role=='student': q=q.where(Course.classroom_id==user.classroom_id)
        if user.role=='teacher': q=q.where(Course.teacher_id==user.id)
        return [course_dict(db,c,user.id if user.role=='student' else None) for c in db.scalars(q).all()]
    @app.get('/api/courses/{course_id}')
    def course_detail(course_id:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
        co=course_access(db,user,course_id)
        lessons=db.scalars(select(Lesson).where(Lesson.course_id==co.id).order_by(Lesson.order_index)).all()
        done={x.lesson_id for x in db.scalars(select(LessonProgress).where(LessonProgress.student_id==user.id)).all()} if user.role=='student' else set()
        return {'course':course_dict(db,co,user.id if user.role=='student' else None),'lessons':[{'id':x.id,'title':x.title,'content':x.content,'done':x.id in done} for x in lessons],'quizzes':[quiz_dict(db,q,user.id if user.role=='student' else None) for q in db.scalars(select(Quiz).where(Quiz.course_id==co.id)).all()]}
    @app.post('/api/lessons/{lesson_id}/complete')
    def complete_lesson(lesson_id:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
        require(user,'student')
        ls=db.get(Lesson,lesson_id)
        if not ls: fail(404,'Урок не найден')
        course_access(db,user,ls.course_id)
        existing=db.scalar(select(LessonProgress).where(LessonProgress.lesson_id==ls.id,LessonProgress.student_id==user.id))
        if existing: return {'ok':True,'already_completed':True,'earned':0}
        db.add(LessonProgress(lesson_id=ls.id,student_id=user.id))
        award(db,user.id,'coin',20,'Пройден урок: '+ls.title,'lesson:'+str(ls.id))
        db.commit()
        return {'ok':True,'already_completed':False,'earned':20}
    @app.get('/api/quizzes')
    def quizzes(user:User=Depends(current_user),db:Session=Depends(get_db)):
        require(user,'student','teacher','admin')
        ids=[c.id for c in db.scalars(select(Course).where(Course.school_id==user.school_id,*([Course.classroom_id==user.classroom_id] if user.role=='student' else []),*([Course.teacher_id==user.id] if user.role=='teacher' else []))).all()]
        if not ids: return []
        return [quiz_dict(db,q,user.id if user.role=='student' else None) for q in db.scalars(select(Quiz).where(Quiz.course_id.in_(ids))).all()]
    @app.get('/api/quizzes/{quiz_id}')
    def quiz_details(quiz_id:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
        q=db.get(Quiz,quiz_id)
        if not q: fail(404,'Тест не найден')
        course_access(db,user,q.course_id)
        return quiz_dict(db,q,user.id if user.role=='student' else None,True)
    @app.post('/api/quizzes/{quiz_id}/submit')
    def submit_quiz(quiz_id:int,data:QuizSubmit,user:User=Depends(current_user),db:Session=Depends(get_db)):
        require(user,'student')
        q=db.get(Quiz,quiz_id)
        if not q: fail(404,'Тест не найден')
        course_access(db,user,q.course_id)
        questions=json.loads(q.questions_json)
        if len(data.answers)!=len(questions): fail(422,'Ответь на каждый вопрос (можно оставить без ответа)')
        if any(a is not None and (a<0 or a>=len(questions[i]['options'])) for i,a in enumerate(data.answers)):
            fail(422,'Некорректный вариант ответа')
        score=sum(a==question['answer'] for a,question in zip(data.answers,questions))
        attempt=QuizAttempt(quiz_id=q.id,student_id=user.id,answers_json=json.dumps(data.answers),score=score,total=len(questions))
        db.add(attempt); db.flush()
        # Retakes are recorded as attempts, but only the best result counts in the gradebook.
        previous_grade=db.scalar(select(Grade).where(Grade.student_id==user.id,Grade.source=='quiz',Grade.source_id==q.id))
        if previous_grade:
            if score/len(questions)>previous_grade.score/previous_grade.max_score:
                previous_grade.score=score;previous_grade.max_score=len(questions)
        else:
            db.add(Grade(student_id=user.id,course_id=q.course_id,label=q.title,score=score,max_score=len(questions),source='quiz',source_id=q.id,feedback='Лучший результат теста'))
        earned=25 if award(db,user.id,'coin',25,'Первый тест: '+q.title,'quiz:'+str(q.id)) else 0
        if score==len(questions) and award(db,user.id,'star',2,'Идеальный тест: '+q.title,'perfect:'+str(q.id)): pass
        db.commit()
        return {'score':score,'total':len(questions),'percent':round(score/len(questions)*100),'earned':earned,'review':[{'prompt':x['prompt'],'selected':a,'answer':x['answer'],'explanation':x['explanation'],'correct':a==x['answer']} for a,x in zip(data.answers,questions)]}
    @app.get('/api/attempts')
    def attempts(user:User=Depends(current_user),db:Session=Depends(get_db)):
        require(user,'student')
        xs=db.scalars(select(QuizAttempt).where(QuizAttempt.student_id==user.id).order_by(QuizAttempt.created_at.desc()).limit(40)).all()
        return [{'id':a.id,'quiz':db.get(Quiz,a.quiz_id).title,'score':a.score,'total':a.total,'percent':round(a.score/a.total*100),'date':timestamp(a.created_at)} for a in xs]
    @app.get('/api/assignments')
    def assignments(user:User=Depends(current_user),db:Session=Depends(get_db)):
        if user.role=='parent': fail()
        ids=[c.id for c in db.scalars(select(Course).where(Course.school_id==user.school_id,*([Course.classroom_id==user.classroom_id] if user.role=='student' else []),*([Course.teacher_id==user.id] if user.role=='teacher' else []))).all()]
        return [assignment_dict(db,a,user.id if user.role=='student' else None) for a in db.scalars(select(Assignment).where(Assignment.course_id.in_(ids))).all()] if ids else []
    @app.post('/api/assignments/{assignment_id}/submit')
    def submit_assignment(assignment_id:int,data:TextInput,user:User=Depends(current_user),db:Session=Depends(get_db)):
        require(user,'student')
        a=db.get(Assignment,assignment_id)
        if not a: fail(404,'Задание не найдено')
        course_access(db,user,a.course_id)
        sub=db.scalar(select(Submission).where(Submission.assignment_id==a.id,Submission.student_id==user.id))
        if sub and sub.status=='graded': fail(409,'Задание уже проверено')
        if sub: sub.content=data.content;sub.status='submitted';sub.submitted_at=utcnow()
        else: db.add(Submission(assignment_id=a.id,student_id=user.id,content=data.content,status='submitted'))
        earned=15 if award(db,user.id,'coin',15,'Сдано задание: '+a.title,'assignment:'+str(a.id)) else 0
        db.commit()
        return {'ok':True,'earned':earned}
    @app.get('/api/grades')
    def grades(student_id:int|None=None,user:User=Depends(current_user),db:Session=Depends(get_db)):
        if user.role=='student': sid=user.id
        elif student_id is not None: sid=authorized_student(db,user,student_id).id
        else: fail(422,'Выбери ученика')
        return [grade_dict(db,g) for g in db.scalars(select(Grade).where(Grade.student_id==sid).order_by(Grade.created_at.desc())).all()]
    @app.get('/api/students/{student_id}/overview')
    def other_overview(student_id:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
        authorized_student(db,user,student_id)
        return student_overview(db,student_id)
    @app.get('/api/events')
    def events(user:User=Depends(current_user),db:Session=Depends(get_db)):
        if user.role=='parent': fail()
        q=select(Event).where(Event.school_id==user.school_id)
        if user.role=='student': q=q.where(Event.classroom_id==user.classroom_id)
        elif user.role=='teacher':
            ids=[x for x in db.scalars(select(Course.classroom_id).where(Course.teacher_id==user.id)).all()]
            q=q.where(Event.classroom_id.in_(ids))
        return [{'id':e.id,'title':e.title,'when_at':timestamp(e.when_at),'category':e.category} for e in db.scalars(q.order_by(Event.when_at)).all()]
    @app.get('/api/notifications')
    def notifications(user:User=Depends(current_user),db:Session=Depends(get_db)):
        return [{'id':n.id,'text':n.text,'date':timestamp(n.created_at),'read':bool(n.is_read)} for n in db.scalars(select(Notification).where(Notification.user_id==user.id).order_by(Notification.created_at.desc()).limit(50)).all()]
    @app.post('/api/notifications/read')
    def mark_read(user:User=Depends(current_user),db:Session=Depends(get_db)):
        ns=db.scalars(select(Notification).where(Notification.user_id==user.id,Notification.is_read==0)).all()
        for n in ns: n.is_read=1
        db.commit(); return {'ok':True}
    @app.get('/api/rewards')
    def rewards(user:User=Depends(current_user),db:Session=Depends(get_db)):
        require(user,'student')
        owned=[r.item_code for r in db.scalars(select(Redemption).where(Redemption.student_id==user.id)).all()]
        txs=db.scalars(select(RewardTransaction).where(RewardTransaction.student_id==user.id).order_by(RewardTransaction.created_at.desc()).limit(40)).all()
        return {'balances':{'coin':balance(db,user.id,'coin'),'star':balance(db,user.id,'star')},'catalog':[{**r,'owned':r['code'] in owned} for r in REWARDS], 'history':[{'reason':t.reason,'currency':t.currency,'amount':t.amount,'date':timestamp(t.created_at)} for t in txs]}
    @app.post('/api/rewards/{code}/redeem')
    def redeem(code:str,user:User=Depends(current_user),db:Session=Depends(get_db)):
        require(user,'student')
        item=next((r for r in REWARDS if r['code']==code),None)
        if not item: fail(404,'Награда не найдена')
        if db.scalar(select(Redemption.id).where(Redemption.student_id==user.id,Redemption.item_code==code)): fail(409,'Награда уже куплена')
        if balance(db,user.id,item['currency'])<item['price']: fail(409,'Недостаточно баллов')
        db.add(Redemption(student_id=user.id,item_code=code))
        db.add(RewardTransaction(student_id=user.id,currency=item['currency'],amount=-item['price'],reason='Покупка: '+item['title'],event_key='purchase:'+code))
        db.commit()
        return {'ok':True,'theme':item['theme']}
    @app.post('/api/assistant')
    async def assistant(data:AssistantInput,user:User=Depends(current_user)):
        require(user,'student')
        message=data.message.lower()
        # Explicitly a curated offline tutor when no external AI provider is configured.
        selected='python'
        for term,category in [('цикл','python'),('range','python'),('спис','python'),('if','python'),('while','python'),('процент','алгебра'),('уравнен','алгебра'),('степен','алгебра'),('скорост','физика'),('сил','физика'),('энерг','физика'),('english','english'),('simple','english'),('grammar','english'),('binary','информатика'),('двоич','информатика'),('поиск','информатика'),('алгоритм','информатика')]:
            if term in message: selected=category;break
        answer,followup=HELP_LIBRARY[selected]
        api_key=os.getenv('OPENAI_API_KEY')
        if api_key:
            try:
                import httpx
                async with httpx.AsyncClient(timeout=15) as client:
                    result=await client.post('https://api.openai.com/v1/responses',headers={'Authorization':'Bearer '+api_key},json={'model':os.getenv('BE_AI_MODEL','gpt-4.1-mini'),'instructions':'You are Bebeshka, a friendly educational tutor for school students. Reply in the language of the user. Give accurate age-appropriate explanations, hints and a practice question. Do not request personal data. Never claim to know the student grades or school data. If uncertain, say so.','input':data.message,'max_output_tokens':400})
                    result.raise_for_status()
                    payload=result.json()
                    text=' '.join(x.get('text','') for out in payload.get('output',[]) for x in out.get('content',[]) if x.get('type')=='output_text').strip()
                    if text: return {'reply':text,'mode':'ai'}
            except Exception: pass
        return {'reply':answer+'\n\n'+followup,'mode':'guide'}

    # Teacher and administrator workflows
    def manage_course(db,user,course_id):
        require(user,'teacher','admin'); return course_access(db,user,course_id,True)
    @app.get('/api/teacher/students')
    def teacher_students(user:User=Depends(current_user),db:Session=Depends(get_db)):
        require(user,'teacher','admin')
        courses=db.scalars(select(Course).where(Course.school_id==user.school_id,*([Course.teacher_id==user.id] if user.role=='teacher' else []))).all()
        cls={c.classroom_id for c in courses}
        return [{'id':s.id,'name':s.name,'classroom_id':s.classroom_id} for s in db.scalars(select(User).where(User.school_id==user.school_id,User.role=='student',User.classroom_id.in_(cls))).all()] if cls else []
    @app.post('/api/teacher/grades')
    def create_grade(data:GradeInput,user:User=Depends(current_user),db:Session=Depends(get_db)):
        co=manage_course(db,user,data.course_id)
        st=authorized_student(db,user,data.student_id)
        if st.classroom_id!=co.classroom_id: fail(403,'Ученик не зачислен в этот класс')
        if data.score>data.max_score: fail(422,'Баллы превышают максимум')
        g=Grade(student_id=st.id,course_id=co.id,label=data.label,score=data.score,max_score=data.max_score,feedback=data.feedback)
        db.add(g)
        db.add(Notification(user_id=st.id,text=f'Новая оценка по предмету «{co.name}»: {data.score:g}/{data.max_score:g}'))
        db.commit()
        return {'ok':True,'id':g.id}
    @app.post('/api/teacher/assignments')
    def create_assignment(data:AssignmentInput,user:User=Depends(current_user),db:Session=Depends(get_db)):
        manage_course(db,user,data.course_id)
        a=Assignment(course_id=data.course_id,title=data.title,instructions=data.instructions,due_at=data.due_at)
        db.add(a);db.commit()
        return {'ok':True,'id':a.id}
    @app.get('/api/teacher/submissions')
    def teacher_submissions(user:User=Depends(current_user),db:Session=Depends(get_db)):
        require(user,'teacher','admin')
        conditions=[Course.school_id==user.school_id]
        if user.role=='teacher': conditions.append(Course.teacher_id==user.id)
        rows=db.execute(select(Submission,Assignment,Course,User).join(Assignment,Submission.assignment_id==Assignment.id).join(Course,Assignment.course_id==Course.id).join(User,Submission.student_id==User.id).where(*conditions).order_by(Submission.submitted_at.desc())).all()
        return [{'id':sub.id,'student':student.name,'title':a.title,'course':co.name,'content':sub.content,'status':sub.status,'feedback':sub.feedback,'score':sub.score,'date':timestamp(sub.submitted_at)} for sub,a,co,student in rows]
    @app.post('/api/teacher/submissions/{submission_id}/review')
    def review_submission(submission_id:int,data:ReviewInput,user:User=Depends(current_user),db:Session=Depends(get_db)):
        require(user,'teacher','admin')
        sub=db.get(Submission,submission_id)
        if not sub: fail(404,'Работа не найдена')
        a=db.get(Assignment,sub.assignment_id)
        manage_course(db,user,a.course_id)
        if sub.status=='graded': fail(409,'Работа уже проверена')
        sub.status='graded';sub.score=data.score;sub.feedback=data.feedback
        db.add(Grade(student_id=sub.student_id,course_id=a.course_id,label=a.title,score=data.score,max_score=100,feedback=data.feedback,source='assignment',source_id=sub.id))
        db.add(Notification(user_id=sub.student_id,text=f'Учитель проверил задание «{a.title}». Результат: {data.score:g}/100'))
        db.commit(); return {'ok':True}
    @app.post('/api/teacher/events')
    def add_event(data:EventInput,user:User=Depends(current_user),db:Session=Depends(get_db)):
        require(user,'teacher','admin')
        classroom=db.get(Classroom,data.classroom_id)
        if not classroom or classroom.school_id!=user.school_id: fail(404,'Класс не найден')
        if user.role=='teacher' and not db.scalar(select(Course.id).where(Course.teacher_id==user.id,Course.classroom_id==classroom.id)): fail()
        e=Event(school_id=user.school_id,classroom_id=classroom.id,title=data.title,when_at=data.when_at,category=data.category)
        db.add(e);db.commit();return {'ok':True,'id':e.id}
    @app.get('/api/admin/classes')
    def classes(user:User=Depends(current_user),db:Session=Depends(get_db)):
        require(user,'teacher','admin')
        q=select(Classroom).where(Classroom.school_id==user.school_id)
        return [{'id':x.id,'name':x.name} for x in db.scalars(q).all()]
    @app.get('/api/admin/users')
    def admin_users(user:User=Depends(current_user),db:Session=Depends(get_db)):
        require(user,'admin')
        return [{'id':x.id,'name':x.name,'email':x.email,'role':x.role,'classroom_id':x.classroom_id} for x in db.scalars(select(User).where(User.school_id==user.school_id).order_by(User.id)).all()]
    @app.post('/api/admin/users')
    def create_user(data:UserInput,user:User=Depends(current_user),db:Session=Depends(get_db)):
        require(user,'admin')
        email=data.email.strip().lower()
        if '@' not in email: fail(422,'Неверный email')
        if db.scalar(select(User.id).where(User.email==email)): fail(409,'Email занят')
        if data.role=='student':
            cls=db.get(Classroom,data.classroom_id)
            if not cls or cls.school_id!=user.school_id: fail(422,'Для ученика требуется класс своей школы')
        nu=User(name=data.name.strip(),email=email,role=data.role,school_id=user.school_id,classroom_id=data.classroom_id if data.role=='student' else None,password_hash=hash_password(data.password))
        db.add(nu);db.commit();return {'ok':True,'id':nu.id}
    @app.post('/api/admin/parent-link')
    def create_parent_link(data:ParentLinkInput,user:User=Depends(current_user),db:Session=Depends(get_db)):
        require(user,'admin')
        st=db.get(User,data.student_id); parent=db.get(User,data.parent_id)
        if not st or not parent or st.school_id!=user.school_id or parent.school_id!=user.school_id or st.role!='student' or parent.role!='parent':fail(422,'Неверная пара')
        if db.scalar(select(ParentLink.id).where(ParentLink.parent_id==parent.id,ParentLink.student_id==st.id)):return {'ok':True,'existing':True}
        db.add(ParentLink(parent_id=parent.id,student_id=st.id));db.commit();return {'ok':True}

    @app.post('/api/admin/classes')
    def create_classroom(data:ClassroomInput,user:User=Depends(current_user),db:Session=Depends(get_db)):
        require(user,'admin')
        if db.scalar(select(Classroom.id).where(Classroom.school_id==user.school_id,Classroom.name==data.name.strip())): fail(409,'Такой класс уже существует')
        cls=Classroom(school_id=user.school_id,name=data.name.strip())
        db.add(cls);db.commit();return {'ok':True,'id':cls.id}
    @app.post('/api/admin/courses')
    def create_course(data:CourseInput,user:User=Depends(current_user),db:Session=Depends(get_db)):
        require(user,'admin')
        cls=db.get(Classroom,data.classroom_id); teacher=db.get(User,data.teacher_id)
        if not cls or cls.school_id!=user.school_id:fail(422,'Класс не найден')
        if not teacher or teacher.school_id!=user.school_id or teacher.role!='teacher':fail(422,'Назначь учителя своей школы')
        co=Course(school_id=user.school_id,classroom_id=cls.id,teacher_id=teacher.id,name=data.name.strip(),description=data.description,color=data.color)
        db.add(co);db.commit();return {'ok':True,'id':co.id}
    @app.post('/api/teacher/lessons')
    def create_lesson(data:LessonInput,user:User=Depends(current_user),db:Session=Depends(get_db)):
        manage_course(db,user,data.course_id)
        order=db.scalar(select(func.count()).select_from(Lesson).where(Lesson.course_id==data.course_id)) or 0
        x=Lesson(course_id=data.course_id,title=data.title.strip(),content=data.content,order_index=order)
        db.add(x);db.commit();return {'ok':True,'id':x.id}
    @app.post('/api/teacher/quizzes')
    def create_quiz(data:QuizInput,user:User=Depends(current_user),db:Session=Depends(get_db)):
        manage_course(db,user,data.course_id)
        questions=[]
        for q in data.questions:
            if not all(x.strip() for x in q.options): fail(422,'Варианты ответов не могут быть пустыми')
            questions.append({'prompt':q.prompt,'options':q.options,'answer':q.answer,'explanation':q.explanation})
        x=Quiz(course_id=data.course_id,title=data.title.strip(),questions_json=json.dumps(questions,ensure_ascii=False))
        db.add(x);db.commit();return {'ok':True,'id':x.id}

    @app.post('/api/me/password')
    def change_password(data:PasswordInput,user:User=Depends(current_user),db:Session=Depends(get_db)):
        if not check_password(data.current_password,user.password_hash): fail(403,'Текущий пароль неверный')
        user.password_hash=hash_password(data.new_password)
        db.commit(); return {'ok':True}
    @app.patch('/api/admin/school')
    def rename_school(data:SchoolInput,user:User=Depends(current_user),db:Session=Depends(get_db)):
        require(user,'admin')
        school=db.get(School,user.school_id)
        school.name=data.name.strip();db.commit();return {'ok':True,'name':school.name}
    @app.post('/api/teacher/announcements')
    def announce(data:AnnouncementInput,user:User=Depends(current_user),db:Session=Depends(get_db)):
        co=manage_course(db,user,data.course_id)
        students=db.scalars(select(User).where(User.school_id==user.school_id,User.role=='student',User.classroom_id==co.classroom_id)).all()
        for st in students:
            db.add(Notification(user_id=st.id,text=data.text))
            parentids=db.scalars(select(ParentLink.parent_id).where(ParentLink.student_id==st.id)).all()
            for parent_id in parentids:
                db.add(Notification(user_id=parent_id,text='Сообщение из класса: '+data.text))
        db.commit(); return {'ok':True,'notified_students':len(students)}
    return app

app=make_app()
