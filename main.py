import asyncio
import threading
import time
import re
import requests
import os
import random
import json
import subprocess
import io
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import (
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
    NoSuchElementException,
    ElementNotInteractableException,
    ElementClickInterceptedException,
)
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Bot,
)
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
)
import phonenumbers
from phonenumbers import region_code_for_number
import pycountry
import speech_recognition as sr
from pydub import AudioSegment
import config

DOWNLOAD_FOLDER = "/tmp" if os.environ.get("DYNO") else "./downloads"
BANNER_PATH = "/tmp/banner.jpg" if os.environ.get("DYNO") else "./banner.jpg"

active_calls = {}
processing_calls = set()
calls_lock = threading.Lock()
refresh_pattern_index = 0
monitoring_active = False
total_calls_detected = 0
bot_start_time = datetime.now()
driver_instance = None
telegram_loop = None


def build_inline_keyboard():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("📡 Number Channel", url=config.NUMBER_CHANNEL_URL),
                InlineKeyboardButton("🔗 Backup Channel", url=config.BACKUP_CHANNEL_URL),
            ],
            [
                InlineKeyboardButton("👨‍💻 Contact Dev", url=config.CONTACT_DEV_URL),
            ],
        ]
    )


def download_banner_image():
    try:
        response = requests.get(config.BANNER_URL, timeout=20)
        if response.status_code == 200:
            with open(BANNER_PATH, "wb") as f:
                f.write(response.content)
            return True
    except Exception as e:
        print(f"Banner download failed: {e}")
    return False


def get_banner_bytes():
    if os.path.exists(BANNER_PATH):
        with open(BANNER_PATH, "rb") as f:
            return f.read()
    return None


def run_coroutine_sync(coro):
    global telegram_loop
    if telegram_loop and telegram_loop.is_running():
        try:
            future = asyncio.run_coroutine_threadsafe(coro, telegram_loop)
            return future.result(timeout=45)
        except Exception as e:
            print(f"Coroutine sync error: {e}")
    return None


async def send_banner_message_async(bot, chat_id, caption, parse_mode="HTML"):
    keyboard = build_inline_keyboard()
    banner_bytes = get_banner_bytes()
    try:
        if banner_bytes:
            msg = await bot.send_photo(
                chat_id=chat_id,
                photo=banner_bytes,
                caption=caption,
                parse_mode=parse_mode,
                reply_markup=keyboard,
            )
        else:
            msg = await bot.send_photo(
                chat_id=chat_id,
                photo=config.BANNER_URL,
                caption=caption,
                parse_mode=parse_mode,
                reply_markup=keyboard,
            )
        return msg.message_id if msg else None
    except Exception as e:
        print(f"Send banner message error: {e}")
        return None


async def send_banner_video_async(bot, chat_id, video_path, caption, parse_mode="HTML"):
    keyboard = build_inline_keyboard()
    banner_bytes = get_banner_bytes()
    try:
        with open(video_path, "rb") as video_file:
            video_data = video_file.read()
        if banner_bytes:
            msg = await bot.send_video(
                chat_id=chat_id,
                video=video_data,
                caption=caption,
                parse_mode=parse_mode,
                reply_markup=keyboard,
                thumbnail=banner_bytes,
                supports_streaming=True,
                width=1280,
                height=720,
            )
        else:
            msg = await bot.send_video(
                chat_id=chat_id,
                video=video_data,
                caption=caption,
                parse_mode=parse_mode,
                reply_markup=keyboard,
                supports_streaming=True,
            )
        return msg.message_id if msg else None
    except Exception as e:
        print(f"Send banner video error: {e}")
        return None


async def delete_message_async(bot, chat_id, message_id):
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass


def send_admin_banner_sync(bot, caption):
    return run_coroutine_sync(
        send_banner_message_async(bot, config.ADMIN_CHAT_ID, caption)
    )


def send_group_banner_sync(bot, caption):
    return run_coroutine_sync(
        send_banner_message_async(bot, config.GROUP_CHAT_ID, caption)
    )


def send_group_video_sync(bot, video_path, caption):
    return run_coroutine_sync(
        send_banner_video_async(bot, config.GROUP_CHAT_ID, video_path, caption)
    )


def delete_admin_msg_sync(bot, msg_id):
    run_coroutine_sync(
        delete_message_async(bot, config.ADMIN_CHAT_ID, msg_id)
    )


def country_to_flag(country_code):
    if not country_code or len(country_code) != 2:
        return "🏳️"
    return "".join(chr(127397 + ord(c)) for c in country_code.upper())


def detect_country(number):
    try:
        clean = re.sub(r"\D", "", number)
        if clean:
            parsed = phonenumbers.parse("+" + clean, None)
            region = region_code_for_number(parsed)
            country = pycountry.countries.get(alpha_2=region)
            if country:
                return country.name, country_to_flag(region)
    except Exception:
        pass
    return "Unknown", "🏳️"


def mask_number(number):
    n = re.sub(r"\D", "", number)
    if len(n) >= 8:
        return n[:4] + "****" + n[-3:]
    return n[:4] + "****" + n[4:]


def create_video_from_audio_and_banner(audio_path, output_path):
    try:
        if not os.path.exists(BANNER_PATH):
            download_banner_image()

        cmd = [
            "ffmpeg",
            "-y",
            "-loop", "1",
            "-i", BANNER_PATH,
            "-i", audio_path,
            "-c:v", "libx264",
            "-tune", "stillimage",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            "-pix_fmt", "yuv420p",
            "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1",
            "-movflags", "+faststart",
            output_path,
        ]

        result = subprocess.run(cmd, capture_output=True, timeout=120)

        if result.returncode == 0 and os.path.exists(output_path):
            size = os.path.getsize(output_path)
            if size > 1000:
                return True

        return False

    except subprocess.TimeoutExpired:
        return False
    except FileNotFoundError:
        return False
    except Exception as e:
        print(f"Video creation error: {e}")
        return False


def extract_otp_from_audio(audio_path):
    try:
        audio = AudioSegment.from_file(audio_path)
        audio = audio.normalize()

        wav_buffer = io.BytesIO()
        audio.export(wav_buffer, format="wav")
        wav_buffer.seek(0)

        recognizer = sr.Recognizer()

        with sr.AudioFile(wav_buffer) as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.5)
            audio_data = recognizer.record(source)

        transcription = None

        try:
            transcription = recognizer.recognize_google(audio_data, language="en-US")
        except sr.UnknownValueError:
            try:
                transcription = recognizer.recognize_google(audio_data, language="es-ES")
            except sr.UnknownValueError:
                return None
            except Exception:
                return None
        except Exception:
            return None

        if not transcription:
            return None

        otp_patterns = [
            r"your[\s]*(?:code|otp|pin|password|verification)[\s]*is[\s]*(\d{4,6})",
            r"(\d{4,6})[\s]*is[\s]*your[\s]*(?:code|otp|pin|password|verification)",
            r"(?:code|otp|pin|password|verification)[\s:]*(\d{4,6})",
            r"código[\s:]*(\d{4,6})",
            r"contraseña[\s:]*(\d{4,6})",
            r"\b(\d{6})\b",
            r"\b(\d{4})\b",
        ]

        for pattern in otp_patterns:
            matches = re.findall(pattern, transcription, re.IGNORECASE)
            if matches:
                candidate = matches[0] if isinstance(matches[0], str) else matches[0]
                if str(candidate).isdigit():
                    return str(candidate)

        return None

    except Exception as e:
        print(f"OTP extraction error: {e}")
        return None


def build_chrome_driver():
    options = Options()
    is_heroku = os.environ.get("DYNO") is not None

    user_agent = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )

    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(f"user-agent={user_agent}")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-infobars")
    options.add_argument("--lang=en-US,en;q=0.9")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    if is_heroku:
        options.binary_location = os.environ.get(
            "GOOGLE_CHROME_BIN", "/app/.apt/usr/bin/google-chrome"
        )
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--remote-debugging-port=9222")

        driver_path = os.environ.get(
            "CHROMEDRIVER_PATH", "/app/.chromedriver/bin/chromedriver"
        )
        service = Service(executable_path=driver_path)
    else:
        from webdriver_manager.chrome import ChromeDriverManager
        service = Service(ChromeDriverManager().install())

    driver = webdriver.Chrome(service=service, options=options)

    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    driver.execute_cdp_cmd(
        "Network.setUserAgentOverride", {"userAgent": user_agent}
    )
    driver.set_page_load_timeout(90)
    driver.implicitly_wait(3)

    return driver


def perform_login(driver):
    try:
        driver.get(config.LOGIN_URL)
        time.sleep(4)

        current_url = driver.current_url
        if "dashboard" in current_url or "live" in current_url or "calls" in current_url:
            return True

        wait = WebDriverWait(driver, 30)

        email_field = None
        email_selectors = [
            (By.CSS_SELECTOR, "input[type='email']"),
            (By.CSS_SELECTOR, "input[name='email']"),
            (By.ID, "email"),
            (By.CSS_SELECTOR, "input[placeholder*='mail' i]"),
            (By.CSS_SELECTOR, "input[autocomplete='email']"),
            (By.CSS_SELECTOR, "input[autocomplete='username']"),
        ]

        for by, selector in email_selectors:
            try:
                email_field = wait.until(EC.element_to_be_clickable((by, selector)))
                if email_field and email_field.is_displayed():
                    break
                email_field = None
            except Exception:
                email_field = None
                continue

        if not email_field:
            page_source = driver.page_source
            if "Login" not in page_source and "Sign In" not in page_source:
                return True
            return False

        driver.execute_script("arguments[0].scrollIntoView(true);", email_field)
        time.sleep(0.5)
        driver.execute_script("arguments[0].focus();", email_field)
        time.sleep(0.3)
        email_field.clear()
        time.sleep(0.2)

        actions = ActionChains(driver)
        actions.click(email_field)
        actions.perform()
        time.sleep(0.3)

        for character in config.ORANGE_EMAIL:
            email_field.send_keys(character)
            time.sleep(random.uniform(0.04, 0.12))

        time.sleep(1)

        password_field = None
        password_selectors = [
            (By.CSS_SELECTOR, "input[type='password']"),
            (By.CSS_SELECTOR, "input[name='password']"),
            (By.ID, "password"),
            (By.CSS_SELECTOR, "input[placeholder*='assword' i]"),
            (By.CSS_SELECTOR, "input[autocomplete='current-password']"),
        ]

        for by, selector in password_selectors:
            try:
                password_field = driver.find_element(by, selector)
                if password_field and password_field.is_displayed():
                    break
                password_field = None
            except Exception:
                password_field = None
                continue

        if not password_field:
            return False

        driver.execute_script("arguments[0].scrollIntoView(true);", password_field)
        time.sleep(0.5)
        driver.execute_script("arguments[0].focus();", password_field)
        time.sleep(0.3)
        password_field.clear()
        time.sleep(0.2)

        actions2 = ActionChains(driver)
        actions2.click(password_field)
        actions2.perform()
        time.sleep(0.3)

        for character in config.ORANGE_PASSWORD:
            password_field.send_keys(character)
            time.sleep(random.uniform(0.04, 0.12))

        time.sleep(1)

        submit_button = None
        submit_selectors = [
            (By.CSS_SELECTOR, "button[type='submit']"),
            (By.CSS_SELECTOR, "input[type='submit']"),
            (By.CSS_SELECTOR, "button.btn-primary"),
            (By.CSS_SELECTOR, "button.login-btn"),
            (By.CSS_SELECTOR, ".login button"),
            (By.CSS_SELECTOR, "form button"),
            (By.XPATH, "//button[contains(translate(text(), 'LOGIN', 'login'), 'login')]"),
            (By.XPATH, "//button[contains(translate(text(), 'SIGN', 'sign'), 'sign')]"),
        ]

        for by, selector in submit_selectors:
            try:
                submit_button = driver.find_element(by, selector)
                if submit_button and submit_button.is_displayed() and submit_button.is_enabled():
                    break
                submit_button = None
            except Exception:
                submit_button = None
                continue

        if submit_button:
            try:
                driver.execute_script("arguments[0].scrollIntoView(true);", submit_button)
                time.sleep(0.5)
                driver.execute_script("arguments[0].click();", submit_button)
            except Exception:
                try:
                    submit_button.click()
                except Exception:
                    try:
                        password_field.submit()
                    except Exception:
                        return False
        else:
            try:
                password_field.submit()
            except Exception:
                return False

        for _ in range(40):
            time.sleep(1)
            url = driver.current_url
            if "dashboard" in url:
                return True
            if "live" in url:
                return True
            if "calls" in url and "login" not in url:
                return True
            if "orangecarrier.com" in url and "login" not in url:
                page = driver.page_source
                if "Logout" in page or "logout" in page or "Live Calls" in page or "Dashboard" in page:
                    return True
            if "login" in url:
                page = driver.page_source
                if "incorrect" in page.lower() or "invalid" in page.lower() or "wrong" in page.lower():
                    return False

        return False

    except Exception as e:
        print(f"Login error: {e}")
        return False


def download_call_audio(driver, call_info, call_uuid):
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        audio_path = os.path.join(
            DOWNLOAD_FOLDER,
            f"audio_{re.sub(r'[^a-zA-Z0-9]', '', call_info['did_number'])}_{timestamp}.mp3",
        )

        try:
            play_script = f'if(typeof window.Play === "function") {{ window.Play("{call_info["did_number"]}", "{call_uuid}"); }}'
            driver.execute_script(play_script)
            time.sleep(6)
        except Exception:
            pass

        browser_cookies = driver.get_cookies()
        session = requests.Session()

        for cookie in browser_cookies:
            session.cookies.set(cookie["name"], cookie["value"])

        ua = driver.execute_script("return navigator.userAgent;")

        headers = {
            "User-Agent": ua,
            "Accept": "audio/mpeg, audio/ogg, audio/wav, audio/*, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": config.CALL_URL,
            "Origin": config.BASE_URL,
            "Sec-Fetch-Dest": "audio",
            "Sec-Fetch-Mode": "no-cors",
            "Sec-Fetch-Site": "same-origin",
            "X-Requested-With": "XMLHttpRequest",
        }

        recording_url = call_info["full_url"]
        response = session.get(
            recording_url, headers=headers, timeout=45, stream=True
        )

        if response.status_code == 200:
            with open(audio_path, "wb") as audio_file:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        audio_file.write(chunk)

            file_size = os.path.getsize(audio_path)
            if file_size > 2000:
                return audio_path
            else:
                os.remove(audio_path)
                return None

        alt_urls = [
            f"{config.BASE_URL}/live/calls/recording/{call_uuid}",
            f"{config.BASE_URL}/recordings/{call_uuid}.mp3",
            f"{config.BASE_URL}/live/calls/audio/{call_info['did_number']}/{call_uuid}",
        ]

        for alt_url in alt_urls:
            try:
                alt_response = session.get(
                    alt_url, headers=headers, timeout=30, stream=True
                )
                if alt_response.status_code == 200:
                    with open(audio_path, "wb") as audio_file:
                        for chunk in alt_response.iter_content(chunk_size=8192):
                            if chunk:
                                audio_file.write(chunk)

                    file_size = os.path.getsize(audio_path)
                    if file_size > 2000:
                        return audio_path
                    else:
                        try:
                            os.remove(audio_path)
                        except Exception:
                            pass
            except Exception:
                continue

        return None

    except Exception as e:
        print(f"Audio download error: {e}")
        return None


def handle_completed_call(driver, call_info, call_uuid, bot):
    global total_calls_detected

    try:
        call_time = call_info["detected_at"].strftime("%Y-%m-%d %I:%M:%S %p")
        masked = mask_number(call_info["did_number"])

        audio_path = download_call_audio(driver, call_info, call_uuid)

        otp_found = None
        if audio_path and os.path.exists(audio_path):
            otp_found = extract_otp_from_audio(audio_path)

        otp_line = ""
        if otp_found:
            otp_line = f"\n└ 🔑 <b>OTP:</b> <code>{otp_found}</code>"

        if audio_path and os.path.exists(audio_path):
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            video_path = os.path.join(
                DOWNLOAD_FOLDER,
                f"video_{re.sub(r'[^a-zA-Z0-9]', '', call_info['did_number'])}_{timestamp}.mp4",
            )

            video_ok = create_video_from_audio_and_banner(audio_path, video_path)

            group_caption = (
                "📳 <b>New Call Captured!</b>\n\n"
                f"└ ⏰ <b>Time:</b> {call_time}\n"
                f"└ {call_info['flag']} <b>Country:</b> {call_info['country']}\n"
                f"└ 📞 <b>Number:</b> <code>{masked}</code>"
                f"{otp_line}\n"
                f"└ 🎙️ <b>Recording:</b> ✅ Attached"
            )

            if video_ok and os.path.exists(video_path):
                send_group_video_sync(bot, video_path, group_caption)
                try:
                    os.remove(video_path)
                except Exception:
                    pass
            else:
                send_group_banner_sync(bot, group_caption)

            try:
                os.remove(audio_path)
            except Exception:
                pass

        else:
            group_caption = (
                "📳 <b>New Call Captured!</b>\n\n"
                f"└ ⏰ <b>Time:</b> {call_time}\n"
                f"└ {call_info['flag']} <b>Country:</b> {call_info['country']}\n"
                f"└ 📞 <b>Number:</b> <code>{masked}</code>"
                f"{otp_line}\n"
                f"└ 🎙️ <b>Recording:</b> ❌ Not Available"
            )
            send_group_banner_sync(bot, group_caption)

    except Exception as e:
        print(f"Handle completed call error: {e}")
    finally:
        with calls_lock:
            processing_calls.discard(call_uuid)


def scan_active_calls(driver, bot):
    global total_calls_detected

    try:
        calls_table = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "LiveCalls"))
        )

        rows = calls_table.find_elements(By.TAG_NAME, "tr")
        current_ids_on_page = set()

        for row in rows:
            try:
                row_id = row.get_attribute("id")
                if not row_id or not row_id.strip():
                    continue

                cells = row.find_elements(By.TAG_NAME, "td")
                if len(cells) < 5:
                    continue

                raw_did = cells[1].text.strip()
                did_number = re.sub(r"\D", "", raw_did)

                if not did_number or len(did_number) < 7:
                    continue

                current_ids_on_page.add(row_id)

                with calls_lock:
                    already_tracked = row_id in active_calls

                if not already_tracked:
                    country_name, flag = detect_country(did_number)
                    full_url = (
                        f"{config.BASE_URL}/live/calls/sound"
                        f"?did={did_number}&uuid={row_id}"
                    )

                    admin_caption = (
                        f"🔴 <b>LIVE CALL DETECTED</b>\n\n"
                        f"└ 📞 <b>Number:</b> <code>{did_number}</code>\n"
                        f"└ {flag} <b>Country:</b> {country_name}\n"
                        f"└ 🔗 <a href='{full_url}'>🎙️ Listen Live</a>\n"
                        f"└ 🕐 <b>Detected:</b> {datetime.now().strftime('%H:%M:%S')}"
                    )

                    admin_msg_id = send_admin_banner_sync(bot, admin_caption)

                    with calls_lock:
                        active_calls[row_id] = {
                            "admin_msg_id": admin_msg_id,
                            "flag": flag,
                            "country": country_name,
                            "did_number": did_number,
                            "call_uuid": row_id,
                            "detected_at": datetime.now(),
                            "last_seen": datetime.now(),
                            "full_url": full_url,
                        }
                        total_calls_detected += 1

                    print(f"New call: {did_number} | {country_name}")

                else:
                    with calls_lock:
                        if row_id in active_calls:
                            active_calls[row_id]["last_seen"] = datetime.now()

            except StaleElementReferenceException:
                continue
            except Exception as row_err:
                print(f"Row processing error: {row_err}")
                continue

        completed_call_ids = []
        with calls_lock:
            for call_id in list(active_calls.keys()):
                if call_id not in current_ids_on_page and call_id not in processing_calls:
                    completed_call_ids.append(call_id)

        for call_id in completed_call_ids:
            with calls_lock:
                if call_id not in active_calls:
                    continue
                call_info = dict(active_calls[call_id])
                processing_calls.add(call_id)
                del active_calls[call_id]

            if call_info.get("admin_msg_id"):
                delete_admin_msg_sync(bot, call_info["admin_msg_id"])

            thread = threading.Thread(
                target=handle_completed_call,
                args=(driver, call_info, call_id, bot),
                daemon=True,
            )
            thread.start()

            print(f"Call ended: {call_info['did_number']}")

    except TimeoutException:
        pass
    except Exception as e:
        print(f"Scan calls error: {e}")


def get_next_refresh_interval():
    global refresh_pattern_index
    interval = config.REFRESH_PATTERN[refresh_pattern_index]
    refresh_pattern_index = (refresh_pattern_index + 1) % len(config.REFRESH_PATTERN)
    return interval


def run_monitoring_loop(loop, bot):
    global monitoring_active, driver_instance, telegram_loop

    telegram_loop = loop
    monitoring_active = True
    driver = None

    while monitoring_active:
        try:
            print("Starting Chrome driver...")
            driver = build_chrome_driver()
            driver_instance = driver

            print("Attempting login...")
            login_success = perform_login(driver)

            if not login_success:
                print("Login failed. Retrying in 30 seconds...")
                try:
                    driver.quit()
                except Exception:
                    pass
                driver = None
                driver_instance = None
                time.sleep(30)
                continue

            print("Login successful! Navigating to live calls...")

            driver.get(config.CALL_URL)
            time.sleep(10)

            try:
                WebDriverWait(driver, 30).until(
                    EC.presence_of_element_located((By.ID, "LiveCalls"))
                )
                print("LiveCalls table found. Monitoring started.")
            except TimeoutException:
                print("LiveCalls table timeout. Continuing anyway...")

            error_count = 0
            last_refresh = datetime.now()
            next_interval = get_next_refresh_interval()

            while monitoring_active and error_count < config.MAX_ERRORS:
                try:
                    now = datetime.now()
                    elapsed = (now - last_refresh).total_seconds()

                    if elapsed > next_interval:
                        print(f"Scheduled refresh after {int(elapsed)}s...")
                        driver.refresh()
                        time.sleep(8)

                        try:
                            WebDriverWait(driver, 20).until(
                                EC.presence_of_element_located((By.ID, "LiveCalls"))
                            )
                        except TimeoutException:
                            pass

                        last_refresh = datetime.now()
                        next_interval = get_next_refresh_interval()

                    current_url = driver.current_url
                    if "login" in current_url:
                        print("Session expired. Re-logging in...")
                        if not perform_login(driver):
                            error_count += 1
                            time.sleep(15)
                            continue
                        driver.get(config.CALL_URL)
                        time.sleep(8)

                    scan_active_calls(driver, bot)
                    error_count = 0
                    time.sleep(config.CHECK_INTERVAL)

                except KeyboardInterrupt:
                    monitoring_active = False
                    break
                except WebDriverException as we:
                    error_count += 1
                    print(f"WebDriver error ({error_count}/{config.MAX_ERRORS}): {we}")
                    time.sleep(10)
                except Exception as loop_err:
                    error_count += 1
                    print(f"Loop error ({error_count}/{config.MAX_ERRORS}): {loop_err}")
                    time.sleep(5)

        except KeyboardInterrupt:
            monitoring_active = False
            break
        except Exception as fatal_err:
            print(f"Fatal monitoring error: {fatal_err}")
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass
                driver = None
                driver_instance = None

        if monitoring_active:
            print("Restarting monitoring in 25 seconds...")
            time.sleep(25)

    print("Monitoring stopped.")


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    caption = (
        "🤖 <b>Orange Carrier Monitor Bot</b>\n\n"
        "Real-time call monitoring system with voice capture and OTP extraction.\n\n"
        "<b>📋 Commands:</b>\n"
        "├ /start — Welcome message\n"
        "├ /status — System status\n"
        "├ /calls — Call statistics\n"
        "├ /uptime — Bot uptime\n"
        "├ /help — Help information\n"
        "└ /restart — Restart monitor (admin)\n\n"
        "<b>⚡ Features:</b>\n"
        "├ 📡 Real-time call detection\n"
        "├ 🎙️ Auto voice recording download\n"
        "├ 🔑 OTP extraction from audio\n"
        "├ 🌍 Country & flag detection\n"
        "├ 📳 Masked number privacy\n"
        "└ 🎬 Audio-video message delivery"
    )
    await send_banner_message_async(context.bot, update.effective_chat.id, caption)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uptime_delta = datetime.now() - bot_start_time
    total_seconds = int(uptime_delta.total_seconds())
    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60

    with calls_lock:
        active_count = len(active_calls)
        processing_count = len(processing_calls)

    status_icon = "🟢 Active" if monitoring_active else "🔴 Inactive"
    driver_icon = "🟢 Running" if driver_instance else "🔴 Stopped"

    caption = (
        f"📊 <b>System Status Report</b>\n\n"
        f"├ 🤖 <b>Monitor:</b> {status_icon}\n"
        f"├ 🌐 <b>Browser:</b> {driver_icon}\n"
        f"├ ⏱️ <b>Uptime:</b> {days}d {hours}h {minutes}m {seconds}s\n"
        f"├ 📞 <b>Active Calls:</b> {active_count}\n"
        f"├ ⚙️ <b>Processing:</b> {processing_count}\n"
        f"├ 📊 <b>Total Detected:</b> {total_calls_detected}\n"
        f"└ 🕐 <b>Server Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    await send_banner_message_async(context.bot, update.effective_chat.id, caption)


async def cmd_calls(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with calls_lock:
        active_count = len(active_calls)
        processing_count = len(processing_calls)

    caption = (
        f"📞 <b>Call Statistics</b>\n\n"
        f"├ 📊 <b>Total Detected:</b> {total_calls_detected}\n"
        f"├ 🔴 <b>Currently Active:</b> {active_count}\n"
        f"├ ⚙️ <b>Processing Queue:</b> {processing_count}\n"
        f"└ 📅 <b>Since:</b> {bot_start_time.strftime('%Y-%m-%d %H:%M:%S')}"
    )
    await send_banner_message_async(context.bot, update.effective_chat.id, caption)


async def cmd_uptime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uptime_delta = datetime.now() - bot_start_time
    total_seconds = int(uptime_delta.total_seconds())
    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60

    caption = (
        f"⏱️ <b>Bot Uptime</b>\n\n"
        f"├ 📅 <b>Started:</b> {bot_start_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"├ 🕐 <b>Now:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"└ ⏳ <b>Running for:</b> {days}d {hours}h {minutes}m {seconds}s"
    )
    await send_banner_message_async(context.bot, update.effective_chat.id, caption)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    caption = (
        "❓ <b>Help & Information</b>\n\n"
        "<b>Bot Commands:</b>\n"
        "├ /start — Welcome & feature overview\n"
        "├ /status — Full system status\n"
        "├ /calls — Call count statistics\n"
        "├ /uptime — How long bot has been running\n"
        "├ /help — This help message\n"
        "└ /restart — Force restart monitor (admin only)\n\n"
        "<b>How It Works:</b>\n"
        "├ 1️⃣ Bot logs into Orange Carrier portal\n"
        "├ 2️⃣ Monitors live calls table in real-time\n"
        "├ 3️⃣ Detects new calls instantly\n"
        "├ 4️⃣ Downloads voice recording when call ends\n"
        "├ 5️⃣ Extracts OTP from audio automatically\n"
        "├ 6️⃣ Creates video from recording + banner\n"
        "└ 7️⃣ Sends alert to group with masked number\n\n"
        "<b>Admin gets:</b> Full number + live listen link\n"
        "<b>Group gets:</b> Masked number + voice video"
    )
    await send_banner_message_async(context.bot, update.effective_chat.id, caption)


async def cmd_restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    admin_id = str(config.ADMIN_CHAT_ID)

    if user_id != admin_id:
        caption = "❌ <b>Unauthorized</b>\n\nThis command is restricted to the admin only."
        await send_banner_message_async(context.bot, update.effective_chat.id, caption)
        return

    global driver_instance

    caption = (
        "🔄 <b>Restarting Monitor...</b>\n\n"
        "The browser will be closed and a fresh session will start.\n"
        "Please allow 30–60 seconds for the restart to complete."
    )
    await send_banner_message_async(context.bot, update.effective_chat.id, caption)

    if driver_instance:
        try:
            driver_instance.quit()
        except Exception:
            pass
        driver_instance = None


async def main():
    global telegram_loop

    os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)
    print("Downloading banner image...")
    download_banner_image()

    app = Application.builder().token(config.BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("calls", cmd_calls))
    app.add_handler(CommandHandler("uptime", cmd_uptime))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("restart", cmd_restart))

    async with app:
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)

        telegram_loop = asyncio.get_event_loop()

        monitor_thread = threading.Thread(
            target=run_monitoring_loop,
            args=(telegram_loop, app.bot),
            daemon=True,
        )
        monitor_thread.start()

        print("Bot is running. Monitoring active.")

        try:
            while True:
                await asyncio.sleep(1)
        except (KeyboardInterrupt, SystemExit):
            global monitoring_active
            monitoring_active = False
            print("Shutting down...")

        await app.updater.stop()
        await app.stop()


if __name__ == "__main__":
    asyncio.run(main())
