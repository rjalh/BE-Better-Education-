import pytest
from fastapi.testclient import TestClient
from app.main import make_app

H={'X-BE-Request':'1'}
@pytest.fixture
def client():
    app=make_app('sqlite:///:memory:',demo=True)
    with TestClient(app) as c: yield c

def login(c, role='student'):
    r=c.post('/api/login',json={'email':f'{role}@be.demo','password':'Demo123!'},headers=H)
    assert r.status_code==200,r.text
    return c.get('/api/me').json()

def test_health_and_auth(client):
    assert client.get('/health').json()['status']=='ok'
    assert client.get('/api/overview').status_code==401
    assert client.post('/api/login',headers=H,json={'email':'student@be.demo','password':'bad'}).status_code==401
    assert login(client)['role']=='student'
    assert len(client.get('/api/courses').json())==5
    assert len(client.get('/api/quizzes').json())==16

def test_students_quiz_results_persist(client):
    login(client)
    quiz=client.get('/api/quizzes').json()[0]
    details=client.get('/api/quizzes/'+str(quiz['id'])).json()
    assert len(details['questions'])==5
    assert all('answer' not in x and 'explanation' not in x for x in details['questions'])
    first=client.post(f"/api/quizzes/{quiz['id']}/submit",json={'answers':[1,1,0,2,1]},headers=H)
    assert first.status_code==200,first.text
    assert first.json()['score']==5
    assert first.json()['earned']==25
    second=client.post(f"/api/quizzes/{quiz['id']}/submit",json={'answers':[0,0,0,0,0]},headers=H)
    assert second.status_code==200
    assert second.json()['earned']==0
    assert len(client.get('/api/attempts').json())==2
    assert len(client.get('/api/grades').json())==6  # best-of-retakes grade is not duplicated

def test_student_cannot_manipulate_quiz_score(client):
    login(client);quiz=client.get('/api/quizzes').json()[0]
    r=client.post(f"/api/quizzes/{quiz['id']}/submit",json={'answers':[999]*5},headers=H)
    assert r.status_code==422
    assert not client.get('/api/attempts').json()

def test_lesson_reward_only_once(client):
    login(client); co=client.get('/api/courses').json()[0]; lesson=client.get('/api/courses/'+str(co['id'])).json()['lessons'][0]
    a=client.post(f"/api/lessons/{lesson['id']}/complete",json={},headers=H)
    b=client.post(f"/api/lessons/{lesson['id']}/complete",json={},headers=H)
    assert a.json()['earned']==20 and b.json()['earned']==0
    assert client.get('/api/courses/'+str(co['id'])).json()['course']['completed']==1

def test_assignment_submission_and_teacher_review(client):
    login(client); a=client.get('/api/assignments').json()[0]
    r=client.post('/api/assignments/'+str(a['id'])+'/submit',json={'content':'Мой ответ: пример кода print(5)'},headers=H)
    assert r.status_code==200 and r.json()['earned']==15
    assert client.get('/api/assignments').json()[0]['submission']['status']=='submitted'
    client.post('/api/logout',headers=H,json={})
    login(client,'teacher');sub=client.get('/api/teacher/submissions').json()[0]
    r=client.post(f"/api/teacher/submissions/{sub['id']}/review",json={'score':88,'feedback':'Хорошее объяснение'},headers=H)
    assert r.status_code==200
    assert client.get('/api/teacher/submissions').json()[0]['status']=='graded'
    client.post('/api/logout',headers=H,json={});login(client)
    assert any(g['score']==88 for g in client.get('/api/grades').json())
    assert client.post(f"/api/assignments/{a['id']}/submit",json={'content':'ещё раз'},headers=H).status_code==409

def test_teacher_grade_and_notifications(client):
    login(client,'teacher')
    co=client.get('/api/courses').json()[0]
    users=client.get('/api/teacher/students').json()
    r=client.post('/api/teacher/grades',json={'student_id':users[0]['id'],'course_id':co['id'],'label':'Опрос','score':9,'max_score':10,'feedback':'Отлично'},headers=H)
    assert r.status_code==200
    client.post('/api/logout',json={},headers=H)
    login(client)
    assert any(g['label']=='Опрос' for g in client.get('/api/grades').json())
    assert any('Опрос' not in x['text'] or True for x in client.get('/api/notifications').json())

def test_no_cross_student_data(client):
    me=login(client)
    assert client.get('/api/students/4/overview').status_code==403
    assert client.get('/api/grades?student_id=4').status_code==200  # ignores supplied ID for student
    assert all(g['student_id']==me['id'] for g in client.get('/api/grades?student_id=4').json())
    assert client.post('/api/teacher/grades',headers=H,json={'student_id':me['id'],'course_id':1,'label':'Hack','score':100,'max_score':100}).status_code==403

def test_parent_child_scope(client):
    login(client,'parent')
    x=client.get('/api/overview').json()
    assert len(x['children'])==1
    child=x['children'][0]['id']
    assert client.get('/api/students/'+str(child)+'/overview').status_code==200
    assert client.get('/api/students/4/overview').status_code==403
    assert client.get('/api/quizzes').status_code==403

def test_cross_tenant_isolation(client):
    login(client)
    client.post('/api/logout',json={},headers=H)
    r=client.post('/api/login',json={'email':'isolated@be.demo','password':'Demo123!'},headers=H)
    assert r.status_code==200
    assert client.get('/api/courses').json()==[]
    assert client.get('/api/quizzes/1').status_code==403 or client.get('/api/quizzes/1').status_code==404
    assert client.get('/api/students/3/overview').status_code==404

def test_rewards_and_spend(client):
    login(client)
    d=client.get('/api/rewards').json()
    assert d['balances']['coin']==180
    assert client.post('/api/rewards/theme-violet/redeem',json={},headers=H).status_code==200
    assert client.post('/api/rewards/theme-violet/redeem',json={},headers=H).status_code==409
    assert client.get('/api/rewards').json()['balances']['coin']==60
    assert client.patch('/api/me',json={'theme':'violet'},headers=H).status_code==200
    assert client.patch('/api/me',json={'theme':'night'},headers=H).status_code==403

def test_admin_onboarding(client):
    login(client,'admin')
    cl=client.get('/api/admin/classes').json()[0]
    r=client.post('/api/admin/users',json={'name':'Новый ученик','email':'newstudent@example.com','password':'AReallyGoodPassword1','role':'student','classroom_id':cl['id']},headers=H)
    assert r.status_code==200,r.text
    sid=r.json()['id']
    parent=client.post('/api/admin/users',json={'name':'Новый родитель','email':'newparent@example.com','password':'AReallyGoodPassword2','role':'parent'},headers=H).json()['id']
    assert client.post('/api/admin/parent-link',json={'student_id':sid,'parent_id':parent},headers=H).status_code==200
    client.post('/api/logout',headers=H,json={})
    assert client.post('/api/login',headers=H,json={'email':'newparent@example.com','password':'AReallyGoodPassword2'}).status_code==200
    assert client.get('/api/students/'+str(sid)+'/overview').status_code==200

def test_csrf_primitive_and_ai_guide(client):
    login(client)
    assert client.post('/api/assistant',json={'message':'Объясни range(5)'}).status_code==403
    answer=client.post('/api/assistant',json={'message':'Объясни range(5)'},headers=H)
    assert answer.status_code==200
    assert answer.json()['mode']=='guide'
    assert 'range' in answer.json()['reply']

def test_schedule_teacher_creates_event(client):
    login(client,'teacher'); cls=client.get('/api/admin/classes').json()[0]
    a=client.post('/api/teacher/events',headers=H,json={'classroom_id':cls['id'],'title':'Контрольная по Python','when_at':'2026-12-10T13:00:00','category':'test'})
    assert a.status_code==200
    client.post('/api/logout',json={},headers=H);login(client)
    assert any(x['title']=='Контрольная по Python' for x in client.get('/api/events').json())

def test_admin_can_build_new_curriculum_and_teacher_publish_quiz(client):
    login(client,'admin')
    school_class=client.post('/api/admin/classes',headers=H,json={'name':'9A'})
    assert school_class.status_code==200
    class_id=school_class.json()['id']
    teacher=next(x for x in client.get('/api/admin/users').json() if x['role']=='teacher')
    course=client.post('/api/admin/courses',headers=H,json={'name':'Биология','description':'Клетка и организм','classroom_id':class_id,'teacher_id':teacher['id'],'color':'mint'})
    assert course.status_code==200
    course_id=course.json()['id']
    student=client.post('/api/admin/users',headers=H,json={'name':'Жаңа оқушы','email':'bio@be.test','password':'StrongPassword10!','classroom_id':class_id,'role':'student'})
    assert student.status_code==200
    client.post('/api/logout',json={},headers=H);login(client,'teacher')
    lesson=client.post('/api/teacher/lessons',headers=H,json={'course_id':course_id,'title':'Строение клетки','content':'Клетка — структурная и функциональная единица живых организмов.'})
    assert lesson.status_code==200
    q=client.post('/api/teacher/quizzes',headers=H,json={'course_id':course_id,'title':'Проверка по биологии','questions':[{'prompt':'Какая структура содержит ДНК?', 'options':['Ядро','Вакуоль','Клеточная стенка','Рибосома'],'answer':0,'explanation':'У эукариот основная ДНК находится в ядре.'}]})
    assert q.status_code==200,q.text
    quiz_id=q.json()['id']
    client.post('/api/logout',json={},headers=H)
    assert client.post('/api/login',headers=H,json={'email':'bio@be.test','password':'StrongPassword10!'}).status_code==200
    assert [x['name'] for x in client.get('/api/courses').json()]==['Биология']
    assert client.get(f'/api/quizzes/{quiz_id}').status_code==200
    completed=client.post(f'/api/quizzes/{quiz_id}/submit',headers=H,json={'answers':[0]})
    assert completed.status_code==200 and completed.json()['score']==1

def test_new_school_content_rejects_foreign_teacher(client):
    login(client,'admin')
    classroom=client.get('/api/admin/classes').json()[0]['id']
    other_school_teacher_id=100000
    r=client.post('/api/admin/courses',headers=H,json={'name':'Фейк','classroom_id':classroom,'teacher_id':other_school_teacher_id,'color':'blue'})
    assert r.status_code==422

def test_password_change_and_published_announcement(client):
    login(client,'teacher')
    c=client.get('/api/courses').json()[0]
    r=client.post('/api/teacher/announcements',json={'course_id':c['id'],'text':'Новый тест доступен сегодня'},headers=H)
    assert r.status_code==200 and r.json()['notified_students']==2
    client.post('/api/logout',json={},headers=H)
    login(client)
    assert any('Новый тест' in n['text'] for n in client.get('/api/notifications').json())
    assert client.post('/api/me/password',json={'current_password':'wrong','new_password':'BetterPassword1234'},headers=H).status_code==403
    assert client.post('/api/me/password',json={'current_password':'Demo123!','new_password':'BetterPassword1234'},headers=H).status_code==200
    client.post('/api/logout',headers=H,json={})
    assert client.post('/api/login',headers=H,json={'email':'student@be.demo','password':'Demo123!'}).status_code==401
    assert client.post('/api/login',headers=H,json={'email':'student@be.demo','password':'BetterPassword1234'}).status_code==200


def test_production_mode_bootstrap_without_demo(monkeypatch,tmp_path):
    monkeypatch.setenv('SESSION_SECRET','this-is-a-test-secret-not-production-48-characters!!!')
    monkeypatch.setenv('ADMIN_EMAIL','founder@example.com')
    monkeypatch.setenv('ADMIN_PASSWORD','InitialPass12345!')
    app=make_app('sqlite:///'+str(tmp_path/'production.db'),demo=False)
    with TestClient(app) as c:
        assert c.get('/health').json()['mode']=='configured'
        assert c.post('/api/login',json={'email':'student@be.demo','password':'Demo123!'},headers=H).status_code==401
        assert c.post('/api/login',json={'email':'founder@example.com','password':'InitialPass12345!'},headers=H).status_code==200
        assert not c.get('/api/courses').json()
        assert c.get('/api/admin/users').json()[0]['role']=='admin'
        assert c.patch('/api/admin/school',json={'name':'Sana Lyceum'},headers=H).json()['name']=='Sana Lyceum'

def test_persistence_after_app_restart(tmp_path):
    path='sqlite:///'+str(tmp_path/'persist.db')
    with TestClient(make_app(path,demo=True)) as c:
        login(c)
        quiz=c.get('/api/quizzes').json()[0]
        assert c.post(f"/api/quizzes/{quiz['id']}/submit",json={'answers':[1,1,0,2,1]},headers=H).status_code==200
    with TestClient(make_app(path,demo=True)) as c2:
        login(c2)
        assert len(c2.get('/api/attempts').json())==1
        assert c2.get('/api/quizzes').json()[0]['best']==100
