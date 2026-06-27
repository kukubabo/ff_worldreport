# M-QA-5: 명시적 import.
import traceback
from datetime import datetime

from sqlalchemy import desc

from plugin import F, ModelBase, db

from .setup import P


class ModelDownloadedEpisode(F.db.Model):
    """다운로드 완료된 에피소드 추적 테이블."""
    __tablename__ = f'{P.package_name}_episodes'
    __table_args__ = {'mysql_collate': 'utf8_general_ci'}
    __bind_key__ = P.package_name

    id = db.Column(db.Integer, primary_key=True)
    video_id = db.Column(db.String(20), unique=True, nullable=False)
    episode_num = db.Column(db.String(10))
    title = db.Column(db.String(500))
    upload_date = db.Column(db.String(10))
    file_path = db.Column(db.String(1000))
    file_size = db.Column(db.BigInteger)
    downloaded_time = db.Column(db.DateTime)

    @classmethod
    def is_downloaded(cls, video_id):
        try:
            with F.app.app_context():
                return F.db.session.query(cls).filter(
                    cls.video_id == video_id).first() is not None
        except Exception as e:
            P.logger.error(f'is_downloaded Exception: {str(e)}')
            return False

    @classmethod
    def delete_all(cls):
        """추적 테이블 전체 비우기. (count, error) 반환.

        사용 시점: 화면에서 "에피소드 추적 초기화" 호출 — 동일 video_id 를 다시 다운로드
        하고 싶을 때. mp4 파일 자체는 디스크에 그대로 두며 yt-dlp 가 덮어쓰는 동작.
        """
        try:
            with F.app.app_context():
                count = F.db.session.query(cls).delete()
                F.db.session.commit()
                return count, None
        except Exception as e:
            P.logger.error(f'delete_all Exception: {str(e)}')
            try:
                F.db.session.rollback()
            except Exception:
                pass
            return 0, str(e)

    @classmethod
    def create(cls, video_id, episode_num, title, upload_date, file_path, file_size=0):
        try:
            with F.app.app_context():
                item = cls()
                item.video_id = video_id
                item.episode_num = episode_num
                item.title = title
                item.upload_date = upload_date
                item.file_path = file_path
                item.file_size = file_size
                item.downloaded_time = datetime.now()
                F.db.session.add(item)
                F.db.session.commit()
                return item
        except Exception as e:
            P.logger.error(f'create Exception: {str(e)}')
            try:
                F.db.session.rollback()
            except Exception:
                pass
            return None


class ModelJobResult(ModelBase):
    """배치 수행 결과 기록 모델."""
    P = P
    __tablename__ = f'{P.package_name}'
    __table_args__ = {'mysql_collate': 'utf8_general_ci'}
    __bind_key__ = P.package_name

    id = db.Column(db.Integer, primary_key=True)
    created_time = db.Column(db.DateTime)
    job_key = db.Column(db.String(100))
    status = db.Column(db.String(50))
    message = db.Column(db.String(500))
    result_data = db.Column(db.Text)

    def __init__(self):
        self.created_time = datetime.now()
        self.status = 'pending'

    @classmethod
    def create(cls, job_key, status, message, result_data=None):
        try:
            with F.app.app_context():
                item = ModelJobResult()
                item.job_key = job_key
                item.status = status
                item.message = message
                item.result_data = result_data
                item.save()
                return item
        except Exception as e:
            cls.P.logger.error(f'Exception:{str(e)}')
            cls.P.logger.error(traceback.format_exc())

    @classmethod
    def get_list(cls):
        return super().get_list(by_dict=True)

    @classmethod
    def make_query(cls, req, order='desc', search='', option1='all', option2='all'):
        with F.app.app_context():
            query = cls.make_query_search(
                F.db.session.query(cls), search, cls.message)

            if option1 != 'all':
                query = query.filter(cls.status == option1)

            if order == 'desc':
                query = query.order_by(desc(cls.created_time))
            else:
                query = query.order_by(cls.created_time)

            return query