import json
import os
import re
import time
import traceback
from datetime import datetime

import yt_dlp

# M-QA-5: 명시적 import.
from plugin import F, PluginModuleBase, jsonify, render_template

from .setup import P
from .model import ModelDownloadedEpisode, ModelJobResult


PLAYLIST_URL = "https://www.youtube.com/playlist?list=PLlHdT83qa_1zKzg0so3sU7FtO-rxao_2H"


class ModuleBasic(PluginModuleBase):
    """
    KBS 특파원보고 세계는 지금 유튜브 자동 다운로더.

    스케줄러에 의해 주기적으로 재생목록을 확인하고,
    새로운 에피소드를 자동으로 다운로드합니다.
    """

    def __init__(self, P):
        super(ModuleBasic, self).__init__(
            P, name='basic',
            first_menu='setting',
            scheduler_desc="특파원보고 세계는 지금 다운로드"
        )
        self.db_default = {
            f'db_version': '1.0',
            # 자동 실행 설정
            f'{self.name}_auto_start': 'False',
            f'{self.name}_interval': '0 6 * * *',
            # DB 관리 설정
            f'{self.name}_db_delete_day': '90',
            f'{self.name}_db_auto_delete': 'False',
            # 알림 설정
            f'use_notify_on_success': 'False',
            f'use_notify_on_failure': 'False',
            # 다운로드 설정
            f'playlist_url': PLAYLIST_URL,
            f'fetch_limit': '20',
            f'download_dir': '/volume2/video/etc/download',
            f'video_format': 'bestvideo[vcodec^=avc1][ext=mp4][height<=1080]+bestaudio[ext=m4a]/best[vcodec^=avc1][ext=mp4][height<=1080]/best[ext=mp4][height<=1080]/best',
            # 마지막 목록 옵션 (UI 상태 유지용)
            f'{P.package_name}_item_last_list_option': '',
        }
        self.web_list_model = ModelJobResult

    def process_menu(self, sub, req):
        arg = P.ModelSetting.to_dict()
        if sub == 'setting':
            arg['is_include'] = F.scheduler.is_include(
                self.get_scheduler_name())
            arg['is_running'] = F.scheduler.is_running(
                self.get_scheduler_name())
        if sub == 'list':
            arg = self.web_list_model.get_list()
        return render_template(
            f'{P.package_name}_{self.name}_{sub}.html', arg=arg)

    def process_command(self, command, arg1, arg2, arg3, req):
        ret = {'ret': 'success'}
        if command == 'manual_execute':
            self.scheduler_function()
            ret['msg'] = '수동 실행이 완료되었습니다.'
        elif command == 'reset_episodes':
            count, err = ModelDownloadedEpisode.delete_all()
            if err is not None:
                ret['ret'] = 'danger'
                ret['msg'] = f'에피소드 추적 초기화 실패: {err}'
            else:
                ret['msg'] = (
                    f'에피소드 추적 {count}건 삭제 완료. '
                    f'다음 실행부터 재다운로드 가능합니다. '
                    f'(주의: 디스크의 mp4 파일은 그대로 — yt-dlp 가 덮어씁니다.)'
                )
        return jsonify(ret)

    def scheduler_function(self):
        """
        스케줄러에 의해 주기적으로 호출되는 메인 배치 로직.

        1. YouTube 재생목록에서 최근 에피소드 메타데이터 조회
        2. DB에서 이미 다운로드된 에피소드 확인
        3. 신규 에피소드만 다운로드
        4. 결과를 DB에 기록
        """
        try:
            P.logger.info("======== World Report 다운로드 시작 ========")

            # 설정 읽기
            playlist_url = P.ModelSetting.get('playlist_url') or PLAYLIST_URL
            fetch_limit = int(P.ModelSetting.get('fetch_limit') or '20')
            download_dir = P.ModelSetting.get('download_dir') or '/home/kukubabo/download'
            video_format = P.ModelSetting.get('video_format') or \
                'bestvideo[vcodec^=avc1][ext=mp4][height<=1080]+bestaudio[ext=m4a]/best[vcodec^=avc1][ext=mp4][height<=1080]/best[ext=mp4][height<=1080]/best'
            # 1. 재생목록 조회
            P.logger.info(f"재생목록 조회 중... (limit={fetch_limit})")
            entries = self._fetch_playlist_entries(playlist_url, fetch_limit)
            P.logger.info(f"본방송 에피소드 {len(entries)}개 조회 완료")

            # 2. 신규 에피소드 필터링
            new_entries = []
            for entry in entries:
                if not ModelDownloadedEpisode.is_downloaded(entry['id']):
                    new_entries.append(entry)

            if not new_entries:
                P.logger.info("신규 에피소드 없음")
                ModelJobResult.create(
                    job_key=f'run_{datetime.now().strftime("%Y%m%d_%H%M%S")}',
                    status='success',
                    message=f'신규 에피소드 없음 (조회: {len(entries)}개)'
                )
                P.logger.info("======== World Report 다운로드 종료 ========")
                return

            P.logger.info(f"신규 에피소드 {len(new_entries)}개 발견")

            # 3. 다운로드
            output_dir = download_dir
            os.makedirs(output_dir, exist_ok=True)

            success_count = 0
            fail_count = 0
            downloaded_episodes = []

            for idx, entry in enumerate(new_entries):
                title = entry['title']
                video_id = entry['id']
                ep_str = self._extract_episode_num(title) or str(idx + 1).zfill(3)

                P.logger.info(f"[{idx + 1}/{len(new_entries)}] E{ep_str} {title} 다운로드 중...")

                try:
                    output_tmpl = os.path.join(
                        output_dir,
                        f"특파원보고 세계는 지금.E{ep_str}."
                        f"%(upload_date>%y%m%d)s.%(height)sp-YT.%(ext)s"
                    )
                    ydl_opts = {
                        "quiet": True,
                        "no_warnings": True,
                        "outtmpl": output_tmpl,
                        "format": video_format,
                        "format_sort": ["vcodec:h264", "acodec:aac", "ext:mp4:m4a"],
                        "merge_output_format": "mp4",
                        "noplaylist": True,
                        "postprocessors": [{
                            "key": "FFmpegVideoRemuxer",
                            "preferedformat": "mp4",
                        }],
                    }
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(entry['url'], download=True)
                        file_path = ydl.prepare_filename(info)
                        file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0

                    ModelDownloadedEpisode.create(
                        video_id=video_id,
                        episode_num=ep_str,
                        title=title,
                        upload_date=entry.get('upload_date', ''),
                        file_path=file_path,
                        file_size=file_size
                    )
                    success_count += 1
                    downloaded_episodes.append(f"E{ep_str} {title}")
                    P.logger.info(f"E{ep_str} {title} 다운로드 완료")

                    # YouTube 요청 간 딜레이
                    if idx < len(new_entries) - 1:
                        time.sleep(3)

                except Exception as e:
                    fail_count += 1
                    P.logger.error(f"E{ep_str} {title} 다운로드 실패: {str(e)}")
                    P.logger.error(traceback.format_exc())

            # 4. 결과 기록
            status = 'success' if fail_count == 0 else ('partial' if success_count > 0 else 'failure')
            msg = f'신규 {len(new_entries)}개 중 성공 {success_count}건, 실패 {fail_count}건'

            result_data = json.dumps({
                'total_checked': len(entries),
                'new_found': len(new_entries),
                'success': success_count,
                'fail': fail_count,
                'episodes': downloaded_episodes,
            }, ensure_ascii=False)

            ModelJobResult.create(
                job_key=f'run_{datetime.now().strftime("%Y%m%d_%H%M%S")}',
                status=status,
                message=msg,
                result_data=result_data
            )

            if fail_count == 0 and P.ModelSetting.get_bool('use_notify_on_success'):
                self._send_notify(f'[{P.package_name}] {msg}')
            elif fail_count > 0 and P.ModelSetting.get_bool('use_notify_on_failure'):
                self._send_notify(f'[{P.package_name}] {msg}')

            P.logger.info("======== World Report 다운로드 종료 ========")

        except Exception as e:
            P.logger.error(f'scheduler_function Exception: {str(e)}')
            P.logger.error(traceback.format_exc())
            try:
                ModelJobResult.create(
                    job_key=f'run_{datetime.now().strftime("%Y%m%d_%H%M%S")}',
                    status='failure',
                    message=f'실행 중 예외 발생: {str(e)}'
                )
            except Exception:
                pass

    # ── 헬퍼 함수 (downloader.py에서 포팅) ──

    @staticmethod
    def _is_regular_episode(title):
        """본방송 여부 판별 — 제목에 (KBS_xxx회) 패턴이 있는 것만 본방송"""
        return bool(re.search(r'KBS_\d+회', title))

    @staticmethod
    def _extract_episode_num(title):
        """영상 제목에서 회차 번호 추출"""
        for pat in [
            r'KBS_(\d+)회',
            r'KBS_Episode\s+(\d+)',
            r'(\d+)회',
            r'Episode\s+(\d+)',
        ]:
            m = re.search(pat, title, re.IGNORECASE)
            if m:
                return m.group(1).zfill(3)
        return None

    @staticmethod
    def _fetch_playlist_entries(playlist_url, fetch_limit):
        """재생목록의 최근 본방송 영상 정보 목록 반환 (비공개·특집 제외)"""
        fetch_count = fetch_limit + 10
        ydl_opts = {
            "quiet": True, "no_warnings": True,
            "extract_flat": True, "skip_download": True,
            "playlistend": fetch_count,
            "extractor_args": {"youtube": {"lang": ["ko"]}},
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(playlist_url, download=False)

        entries = []
        for entry in info.get("entries", []):
            if not entry:
                continue
            title = entry.get("title", "")
            if not ModuleBasic._is_regular_episode(title):
                continue
            entries.append({
                "id": entry.get("id", ""),
                "title": title,
                "url": entry.get("url") or f"https://www.youtube.com/watch?v={entry.get('id', '')}",
                "upload_date": entry.get("upload_date", ""),
                "duration": entry.get("duration"),
            })
            if len(entries) >= fetch_limit:
                break
        return entries

    def _send_notify(self, message):
        """알림 발송."""
        try:
            from tool import ToolNotify
            ToolNotify.send_message(
                message, message_id=f'bot_{P.package_name}')
        except Exception:
            pass