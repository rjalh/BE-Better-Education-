from datetime import datetime, timezone
from sqlalchemy import String, Integer, ForeignKey, Text, DateTime, UniqueConstraint, Float
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow(): return datetime.now(timezone.utc).replace(tzinfo=None)
class Base(DeclarativeBase): pass

class School(Base):
    __tablename__='schools'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
class Classroom(Base):
    __tablename__='classrooms'
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey('schools.id'), index=True)
    name: Mapped[str] = mapped_column(String(70))
class User(Base):
    __tablename__='users'
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey('schools.id'), index=True)
    classroom_id: Mapped[int | None] = mapped_column(ForeignKey('classrooms.id'), nullable=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20))
    theme: Mapped[str] = mapped_column(String(40), default='sky')
    locale: Mapped[str] = mapped_column(String(5), default='ru')
class ParentLink(Base):
    __tablename__='parent_links'
    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    student_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    __table_args__=(UniqueConstraint('parent_id','student_id'),)
class Course(Base):
    __tablename__='courses'
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey('schools.id'), index=True)
    classroom_id: Mapped[int] = mapped_column(ForeignKey('classrooms.id'))
    teacher_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(240))
    color: Mapped[str] = mapped_column(String(20), default='blue')
class Lesson(Base):
    __tablename__='lessons'
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey('courses.id'), index=True)
    title: Mapped[str] = mapped_column(String(150))
    content: Mapped[str] = mapped_column(Text)
    order_index: Mapped[int] = mapped_column(Integer)
class LessonProgress(Base):
    __tablename__='lesson_progress'
    id: Mapped[int] = mapped_column(primary_key=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey('lessons.id'))
    student_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    completed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __table_args__=(UniqueConstraint('lesson_id','student_id'),)
class Quiz(Base):
    __tablename__='quizzes'
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey('courses.id'), index=True)
    title: Mapped[str] = mapped_column(String(160))
    questions_json: Mapped[str] = mapped_column(Text)
class QuizAttempt(Base):
    __tablename__='quiz_attempts'
    id: Mapped[int] = mapped_column(primary_key=True)
    quiz_id: Mapped[int] = mapped_column(ForeignKey('quizzes.id'))
    student_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    answers_json: Mapped[str] = mapped_column(Text)
    score: Mapped[int] = mapped_column(Integer)
    total: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
class Assignment(Base):
    __tablename__='assignments'
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey('courses.id'))
    title: Mapped[str] = mapped_column(String(160))
    instructions: Mapped[str] = mapped_column(Text)
    due_at: Mapped[datetime] = mapped_column(DateTime)
class Submission(Base):
    __tablename__='submissions'
    id: Mapped[int] = mapped_column(primary_key=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey('assignments.id'))
    student_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default='submitted')
    feedback: Mapped[str] = mapped_column(Text, default='')
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __table_args__=(UniqueConstraint('assignment_id','student_id'),)
class Grade(Base):
    __tablename__='grades'
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey('courses.id'))
    label: Mapped[str] = mapped_column(String(160))
    score: Mapped[float] = mapped_column(Float)
    max_score: Mapped[float] = mapped_column(Float, default=100)
    feedback: Mapped[str] = mapped_column(Text, default='')
    source: Mapped[str] = mapped_column(String(20), default='teacher')
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
class Event(Base):
    __tablename__='events'
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey('schools.id'))
    classroom_id: Mapped[int] = mapped_column(ForeignKey('classrooms.id'))
    title: Mapped[str] = mapped_column(String(160))
    when_at: Mapped[datetime] = mapped_column(DateTime)
    category: Mapped[str] = mapped_column(String(30), default='lesson')
class Notification(Base):
    __tablename__='notifications'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    text: Mapped[str] = mapped_column(String(280))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    is_read: Mapped[int] = mapped_column(Integer, default=0)
class RewardTransaction(Base):
    __tablename__='reward_transactions'
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    currency: Mapped[str] = mapped_column(String(10))
    amount: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(200))
    event_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __table_args__=(UniqueConstraint('student_id','event_key'),)
class Redemption(Base):
    __tablename__='redemptions'
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    item_code: Mapped[str] = mapped_column(String(60))
    purchased_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __table_args__=(UniqueConstraint('student_id','item_code'),)
