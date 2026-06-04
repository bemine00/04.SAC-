import streamlit as st
import sqlite3
import pandas as pd
import zipfile
import io
import os
import requests  # <--- [추가] API 호출을 위해 반드시 필요!
from datetime import datetime, timedelta
from requests.auth import HTTPBasicAuth  # <--- 이 줄을 반드시 추가해야 합니다!
from datetime import datetime
from PIL import Image
from datetime import datetime
import pytz

# --- 설정 및 경로 ---
st.set_page_config(page_title="용접작업안전승인관리시스템", layout="wide")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
DB_NAME = os.path.join(BASE_DIR, "weldpass_master.db")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# [추가] URL 파라미터 읽기 (바로가기 기능)
params = st.query_params
target_code = params.get("code")

# CSS 디자인
st.markdown(
    """
    <style>
    /* 전체 배경을 연한 회색으로 설정하여 가독성 향상 */
    .stApp {
        background-color: #F8FAFC;
    }

    /* 메인 헤더: 흰색 배경에 부드러운 그림자 효과 */
    .main-header {
        background-color: #FFFFFF;
        padding: 25px;
        border-radius: 15px;
        border-left: 10px solid #65A30D; /* 좀 더 차분한 그린 컬러 */
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
        margin-bottom: 30px;
    }
    
    .main-header h1 {
        color: #1E293B; /* 짙은 남색 텍스트 */
        font-weight: 700;
    }

    /* 카드 디자인: 흰색 배경에 연한 테두리 */
    .task-card {
        background-color: #FFFFFF;
        padding: 20px;
        border-radius: 12px;
        border: 1px solid #E2E8F0;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
        margin-bottom: 15px;
        color: #334155;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# --- 유틸리티 함수 ---
def kor_time():
    # 한국 시간은 UTC보다 9시간 빠릅니다.
    return datetime.utcnow() + timedelta(hours=9)

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS logs 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, service_code TEXT, site TEXT, 
                  eng_name TEXT, eng_phone TEXT, status TEXT, admin_comment TEXT, 
                  created_at TEXT, approved_at TEXT)""")
    # [추가] 관리자 연락처 테이블 생성
    c.execute("""CREATE TABLE IF NOT EXISTS admin_users 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  name TEXT, 
                  phone TEXT)""")
    # (선택) 초기 관리자가 한 명도 없다면 기본 관리자 추가
    c.execute("SELECT COUNT(*) FROM admin_users")
    if c.fetchone()[0] == 0:
        c.execute(
            "INSERT INTO admin_users (name, phone) VALUES (?, ?)",
            ("기본관리자", "01020858775"),
        )

    try:
        c.execute("ALTER TABLE logs ADD COLUMN sms_status TEXT DEFAULT '미발송'")
    except:
        pass
    conn.commit()
    conn.close()


def save_optimized_image(uploaded_file, save_path):
    img = Image.open(uploaded_file)
    width_percent = 1024 / float(img.size[0])
    hsize = int((float(img.size[1]) * float(width_percent)))
    img = img.resize((1024, hsize), Image.Resampling.LANCZOS)
    img.convert("RGB").save(save_path, "JPEG", quality=85)


def get_access_token():
    url = "https://message.ppurio.com/v1/token"
    # 1. 인증 정보 가져오기
    user_id = st.secrets["PPURIO_USER"]
    api_key = st.secrets["PPURIO_TOKEN"]
    
    # 2. 인증 객체 생성
    auth = HTTPBasicAuth(user_id, api_key)
    
    # 3. 토큰 발급 요청
    response = requests.post(url, auth=auth)
    
    if response.status_code == 200:
        return response.json().get("token")
    else:
        # 실패 시에는 적절한 에러 로그만 남기거나 멈추는 것이 좋습니다.
        return None


def get_admin_phones():
    conn = sqlite3.connect(DB_NAME)
    # 테이블이 없다면 생성 방지를 위해 try-except 사용 가능
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT phone FROM admin_users")
        phones = [row[0] for row in cursor.fetchall()]
    except:
        phones = ["01020858775"]  # 기본 관리자 번호 (테이블 없을 시)
    finally:
        conn.close()
    return phones


# [추가] 관리자 전체에게 발송하는 함수
def notify_all_admins(log_id, message_text):
    phones = get_admin_phones()
    for phone in phones:
        send_prio_sms(log_id, phone, message_text)


def send_prio_sms(log_id, to_phone, message_text):
    print("DEBUG: [함수 진입] 문자 발송 시작") 
    token = get_access_token()
    
    if not token:
        print("DEBUG: [실패] 토큰을 가져오지 못했습니다.")
        return False
    
    print(f"DEBUG: [진행] 토큰 획득 성공: {token[:10]}...") 

    url = "https://message.ppurio.com/v1/message"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    payload = {
        "account": "dajontec",
        "messageType": "LMS" if len(message_text.encode("euc-kr")) > 80 else "SMS",
        "targets": [{"to": to_phone.replace("-", "")}],
        "from": "15773951",
        "content": message_text,
        "duplicateFlag": "N",
        "targetCount": 1,
        "refKey": str(log_id),
    }

    try:
        print("DEBUG: [요청] 뿌리오 서버로 전송 시도...")
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        print(f"DEBUG: [응답] 상태코드={response.status_code}, 상세={response.text}")
        
        status = "성공" if response.status_code == 200 else f"실패({response.status_code})"
    except Exception as e:
        print(f"DEBUG: [예외] 요청 중 에러 발생: {str(e)}")
        status = f"오류"
        
    return status == "성공"

# --- 인증 함수 ---
def check_password():
    if "password_correct" not in st.session_state:
        st.session_state["password_correct"] = False
    if not st.session_state["password_correct"]:
        pwd = st.text_input("관리자 비밀번호를 입력하세요", type="password")
        if st.button("로그인"):
            if pwd == "8775":  # 비밀번호 설정
                st.session_state["password_correct"] = True
                st.rerun()
            else:
                st.error("비밀번호가 틀렸습니다.")
        return False
    return True


init_db()

# 사이드바에 로고 배치
st.sidebar.image("회사로고캡처(신_150픽셀).jpg", use_container_width=True)
st.sidebar.title("용접 작업 승인 관리시스템")

# --- 메인 메뉴 ---
st.markdown(
    '<div class="main-header"><h1>서남부 ESI·유지보수 용접 작업 승인 관리시스템</h1></div>',
    unsafe_allow_html=True,
)
menu = st.sidebar.selectbox(
    "📂 서비스 메뉴", ["엔지니어 요청", "관리자 대시보드", "관리자용 데이터 센터"]
)

# [1. 엔지니어 요청]
if menu == "엔지니어 요청":
    st.subheader("📝 용접 현장 안전 승인 요청")
    # [추가] 촬영 기준 안내 가이드
    with st.expander("📌 작업 전 필수 안전 준수 및 촬영 기준 (클릭하여 확인)"):

        st.markdown("""
        **안전 조치 후 사진을 업로드해 주세요.**
        1. **방화포 설치(용접부위)**
        2. **방화포 설치(바닥)**
        3. **소화기 비치**
        4. **가연물 제거**
        
        → 모든 준비 후 관리자에게 승인요청을 보내주세요!               
        → 승인 완료 후 작업을 실시하여야합니다!
        """)

    with st.form("engineer_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        code = c1.text_input("서비스 코드")
        site = c1.selectbox("거점명", ["대구", "대전", "양산", "광주", "제주"])
        eng_name = c2.text_input("엔지니어 성명")
        eng_phone = c2.text_input("연락처")

        p1, p2, p3 = st.columns(3)
        img1, img2, img3 = (
            p1.file_uploader("[1] 방화포 설치"),
            p2.file_uploader("[2] 소화기 비치"),
            p3.file_uploader("[3] 가연물 제거"),
        )

        if st.form_submit_button("🛡️ 승인 요청 전송"):
            # 0. 중복 코드 확인 로직
            conn = sqlite3.connect(DB_NAME)
            is_duplicate = conn.execute(
                "SELECT id FROM logs WHERE service_code = ?", (code,)
            ).fetchone()
            conn.close()

            if is_duplicate:
                st.error(f"⚠️ 이미 등록된 서비스 코드입니다. ({code})")
            elif not (img1 or img2 or img3):
                st.error("⚠️ 최소한 1장 이상의 안전 조치 사진을 업로드해주세요.")
            else:
                # 1. DB 저장
                conn = sqlite3.connect(DB_NAME)
                c = conn.cursor()
                # 한국 시간 구하기
                kst = pytz.timezone('Asia/Seoul')
                kor_time = datetime.now(kst).strftime("%Y-%m-%d %H:%M:%S")
                c.execute(
                    "INSERT INTO logs (service_code, site, eng_name, eng_phone, status, created_at) VALUES (?,?,?,?,?,?)",
                    (
                        code,
                        site,
                        eng_name,
                        eng_phone,
                        "대기",
                        kor_time,
                    ),
                )
                conn.commit()
                conn.close()

                # 2. 사진 저장 (파일명: 서비스코드_순번.jpg)
                safe_code = "".join([c for c in code if c.isalnum() or c in ("-", "_")])
                images = [(img1, 1), (img2, 2), (img3, 3)]
                for img, idx in images:
                    if img is not None:
                        save_optimized_image(
                            img, os.path.join(UPLOAD_DIR, f"{safe_code}_{idx}.jpg")
                        )

                # 3. 알림 발송 (문자 간격 주의하여 줄바꿈 적용)
                app_url = "https://jjpg4deafdyh9jvtc8ync9.streamlit.app/"
                admin_msg = (
                    f"[서남부 SAC] 용접 안전 승인 요청\n"
                    f"요청자: {eng_name}\n"
                    f"거점: {site}\n"
                    f"서비스코드: {code}\n"
                    f"바로가기: {app_url}?code={code}\n"
                    f"관리자 페이지에서 확인 후 승인해 주세요."
                )
                send_prio_sms(code, "01020858775", admin_msg)

                st.success(f"✅ 요청 완료: {code}")

# [2. 관리자 대시보드 및 3. 데이터 센터 (인증 필요)]
elif menu in ["관리자 대시보드", "관리자용 데이터 센터"]:
    if check_password():
        if menu == "관리자 대시보드":
            st.subheader("🔍 대기 중인 승인 요청")
            conn = sqlite3.connect(DB_NAME)
            df = pd.read_sql_query(
                "SELECT * FROM logs WHERE status = '대기' ORDER BY id DESC", conn
            )
            conn.close()

            if df.empty:
                st.info("대기 중인 요청이 없습니다.")
            else:
                for _, row in df.iterrows():
                    dt = datetime.strptime(row["created_at"], "%Y-%m-%d %H:%M:%S")
                    summary_data = pd.DataFrame(
                        {
                            "NO": [row["id"]],
                            "거점": [row["site"]],
                            "설치일": [dt.strftime("%Y-%m-%d")],
                            "승인요청자": [row["eng_name"]],
                            "용접작업": ["대상"],
                            "요청시간": [dt.strftime("%H:%M:%S")],
                            "안전조치": ["사진확인"],
                            "용접작업처리결과": [row["status"]],
                        }
                    )
                    st.table(summary_data)
                    cols = st.columns(3)
                    for i in range(1, 4):
                        path = os.path.join(UPLOAD_DIR, f"{row['id']}_{i}.jpg")
                        if os.path.exists(path):
                            cols[i - 1].image(
                                path,
                                caption=[
                                    "[1] 방화포 설치",
                                    "[2] 소화기 비치",
                                    "[3] 가연물 제거",
                                ][i - 1],
                                use_container_width=True,
                            )

                    cmt = st.text_input("관리자 코멘트", key=f"cmt_{row['id']}")
                    c1, c2 = st.columns(2)

                    # [수정된 승인 버튼 로직]
                    if c1.button("✅ 승인", key=f"app_{row['id']}"):
                        # 1. 먼저 문자 발송 시도
                        msg = f"[작업승인] {row['service_code']} 현장 용접 작업 승인"
                        sms_success = send_prio_sms(row["id"], row["eng_phone"], msg)
                        
                        new_status = "성공" if sms_success else "실패"
                        
                        # 2. DB 업데이트 (문자 상태 포함)
                        conn = sqlite3.connect(DB_NAME)
                        conn.execute(
                            "UPDATE logs SET status='승인', admin_comment=?, approved_at=?, sms_status=? WHERE id=?",
                            (cmt, datetime.now().strftime("%H:%M:%S"), new_status, row["id"]),
                        )
                        conn.commit()
                        conn.close()
                        
                        st.success(f"승인 처리 완료 (문자발송: {new_status})")
                        st.rerun()

                    # 이 'if'가 위 'if'와 정확히 같은 선상에 있어야 합니다!
                    if c2.button("❌ 작업중지", key=f"rej_{row['id']}"):
                        conn = sqlite3.connect(DB_NAME)
                        conn.execute(
                            "UPDATE logs SET status='반려', admin_comment=? WHERE id=?",
                            (cmt, row["id"]),
                        )
                        conn.commit()
                        conn.close()

                        # [알림] 반려 문자 발송
                        msg = (
                            f"[작업반려] {row['site']} 현장 용접 작업이 반려되었습니다."
                        )
                        send_prio_sms(row["id"], row["eng_phone"], msg)

                        st.error("작업 반려 및 문자 발송 완료")
                        st.rerun()
                    st.markdown("---")

        elif menu == "관리자용 데이터 센터":
            # --- [여기 삽입하세요!] ---
            st.subheader("👨‍💼 관리자 연락처 관리")
            c1, c2 = st.columns([2, 1])
            with c1:
                admin_name = st.text_input("관리자 이름")
                admin_phone = st.text_input("관리자 연락처 (숫자만 입력)")
            with c2:
                st.write("")  # 간격 맞춤
                st.write("")
                if st.button("➕ 관리자 추가"):
                    if admin_name and admin_phone:
                        conn = sqlite3.connect(DB_NAME)
                        conn.execute(
                            "INSERT INTO admin_users (name, phone) VALUES (?, ?)",
                            (admin_name, admin_phone),
                        )
                        conn.commit()
                        conn.close()
                        st.success("추가 완료")
                        st.rerun()

            # 현재 등록된 관리자 목록 (삭제 기능 포함)
            conn = sqlite3.connect(DB_NAME)
            admin_df = pd.read_sql_query("SELECT * FROM admin_users", conn)
            conn.close()

            with st.expander("📝 등록된 관리자 목록 보기"):
                st.dataframe(admin_df, use_container_width=True)
                del_admin_id = st.number_input("삭제할 관리자 ID", min_value=1, step=1)
                if st.button("🗑️ 관리자 삭제"):
                    conn = sqlite3.connect(DB_NAME)
                    conn.execute(
                        "DELETE FROM admin_users WHERE id = ?", (del_admin_id,)
                    )
                    conn.commit()
                    conn.close()
                    st.rerun()
            st.markdown("---")
            # --- [삽입 끝] ---

            st.subheader("📊 전체 관리대장")
            conn = sqlite3.connect(DB_NAME)
            df = pd.read_sql_query("SELECT * FROM logs ORDER BY id DESC", conn)
            conn.close()

            display_df = pd.DataFrame(
                {
                    "NO": df["id"],
                    "거점": df["site"],
                    "서비스코드": df["service_code"],  # 👈 서비스코드 열 추가
                    "설치일": df["created_at"].str.split(" ").str[0],
                    "승인요청자": df["eng_name"],
                    "용접작업": "대상",
                    "요청시간": df["created_at"].str.split(" ").str[1],
                    "안전조치": "사진확인완료",
                    "처리결과": df["status"],
                    "승인시간": df["approved_at"].fillna("-"),
                    "문자상태": df["sms_status"],  # 👈 추가
                }
            )
            # --- 여기서 인덱스를 NO로 설정하여 앞의 공란을 제거합니다 ---
            display_df = display_df.set_index("NO")
            # 화면에 표 출력 (인덱스가 NO가 되어 왼쪽 공란 없이 출력됩니다)
            st.dataframe(display_df, use_container_width=True)

            excel_df = display_df.copy()

            # [수정] 3개 컬럼 대신 "사진첨부" 컬럼 1개로 합치기
            def check_any_image_exists(code):
                safe_code = "".join([c for c in code if c.isalnum() or c in ("-", "_")])
                # 1, 2, 3번 사진 중 하나라도 있으면 True 반환
                for i in range(1, 4):
                    if os.path.exists(os.path.join(UPLOAD_DIR, f"{safe_code}_{i}.jpg")):
                        return "○"
                return "×"

            # 서비스 코드를 기준으로 하나라도 사진이 있는지 확인
            excel_df["사진첨부"] = df["service_code"].apply(check_any_image_exists)

            path = "WeldPass_Data_Safety_Log.xlsx"
            excel_df.to_excel(path, index=False)
            with open(path, "rb") as f:
                st.download_button("📥 엑셀 관리대장 다운로드", f, path)

            st.markdown("---")
            delete_id = st.number_input("삭제할 ID 입력", min_value=1, step=1)
            if st.button("🚨 데이터 영구 삭제"):
                conn = sqlite3.connect(DB_NAME)
                # 1. 삭제할 ID의 서비스 코드를 먼저 조회합니다.
                row = conn.execute(
                    "SELECT service_code FROM logs WHERE id = ?", (delete_id,)
                ).fetchone()

                if row:
                    target_code = row[0]
                    # 파일명으로 저장했던 방식과 동일하게 안전한 파일명 생성
                    safe_code = "".join(
                        [c for c in target_code if c.isalnum() or c in ("-", "_")]
                    )

                    # 2. DB에서 데이터 삭제
                    conn.execute("DELETE FROM logs WHERE id = ?", (delete_id,))
                    conn.commit()
                    conn.close()

                    # 3. 사진 파일 삭제 (safe_code 사용)
                    for i in range(1, 4):
                        p = os.path.join(UPLOAD_DIR, f"{safe_code}_{i}.jpg")
                        if os.path.exists(p):
                            os.remove(p)

                    st.success(f"ID {delete_id} (코드: {target_code}) 삭제 완료")
                    st.rerun()
                else:
                    conn.close()
                    st.error("해당 ID의 데이터를 찾을 수 없습니다.")

            # --- [추가] 날짜별 증거 자료 선택 다운로드 기능 ---
            st.subheader("📁 일자별 증거 자료 선택 다운로드")

            # DB에서 존재하는 모든 날짜 리스트 가져오기
            conn = sqlite3.connect(DB_NAME)
            # 날짜만 추출하여 중복 제거 후 내림차순 정렬
            date_rows = conn.execute("SELECT created_at FROM logs").fetchall()
            date_list = sorted(
                list(set([row[0].split(" ")[0] for row in date_rows])), reverse=True
            )
            conn.close()

            if not date_list:
                st.info("데이터가 없습니다.")
            else:
                # 1. 날짜 선택
                selected_date = st.selectbox("다운로드할 날짜를 선택하세요", date_list)

                # 2. 선택된 날짜의 데이터만 압축
                if st.button(f"📦 {selected_date} 자료만 다운로드"):
                    zip_buffer = io.BytesIO()
                    with zipfile.ZipFile(zip_buffer, "w") as zip_file:
                        conn = sqlite3.connect(DB_NAME)
                        # 선택한 날짜의 로그 데이터만 조회
                        logs = conn.execute(
                            "SELECT id FROM logs WHERE created_at LIKE ?",
                            (f"{selected_date}%",),
                        ).fetchall()
                        conn.close()

                        found_files = False
                        for (log_id,) in logs:
                            for i in range(1, 4):
                                file_name = f"{log_id}_{i}.jpg"
                                file_path = os.path.join(UPLOAD_DIR, file_name)
                                if os.path.exists(file_path):
                                    zip_file.write(file_path, arcname=file_name)
                                    found_files = True

                        if not found_files:
                            st.warning("해당 날짜에 저장된 사진 파일이 없습니다.")
                        else:
                            st.download_button(
                                label=f"📥 {selected_date}_증거_다운로드.zip",
                                data=zip_buffer.getvalue(),
                                file_name=f"Evidence_{selected_date}.zip",
                                mime="application/zip",
                            )
                if st.sidebar.button("⚠️ 데이터 전체 초기화 (운영 전용)"):
                    # DB 삭제 및 생성 로직 추가
                    # UPLOAD_DIR의 모든 파일 삭제 로직 추가
                    st.warning("데이터가 초기화되었습니다. 앱을 재시작하세요.")

# 네트워크 테스트 코드 (임시)
# if st.button("🌐 통신 테스트"):
#    try:
#        res = requests.get("https://www.google.com", timeout=5)
#        st.write("인터넷 연결 상태:", res.status_code)
#    except Exception as e:
#        st.error(f"연결 실패: {e}")
