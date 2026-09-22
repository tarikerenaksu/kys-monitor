# KYS Monitor - ESP32-S3 / MicroPython
# ============================================================
# IMPORTANT SAFETY / USAGE NOTICE
#
# This project is provided "AS IS" and without any warranty.
# Use it at your own risk. The project author accepts no
# responsibility for damage to the ESP32-S3, onboard RGB LED,
# flash storage, connected hardware, accounts, data, or any
# other direct/indirect consequence resulting from use of this
# software or following these instructions.
#
# RGB LED WARNING:
# The onboard RGB LED is driven with a custom SPI/WS2812 method
# because the LED behavior could not be made reliable during
# development. The LED output is hardware-dependent and may be
# unsafe for a particular board/revision. Incorrect electrical
# behavior, timing, or hardware differences MAY damage the RGB LED.
#
# FLASH WARNING:
# The monitor persists settings, state, application data, change
# history and cached details to the ESP32 flash filesystem. Even
# though writes are deliberately reduced when possible, repeated
# read/write cycles can consume flash write endurance. Excessive
# wear can lead to filesystem corruption or device/storage failure.
# Back up important data and use this project only on hardware
# where flash wear is acceptable.
#
# TEKNOFEST NOTICE:
# If TEKNOFEST or the relevant organizing body requests removal
# of this project or its software, the author may remove it from
# the public repository.
# ============================================================

# main.py
# ============================================================
# KYS Monitor - ESP32-S3 / MicroPython
# v13 - Remove gold left-edge page glow; preserve v12 filters
# RAM-optimized base + original full feature set
#
# Hardware note: the integrated RGB LED driver is board-dependent.
# Flash note: persistent state is stored on the device filesystem;
# avoid unnecessary writes because Flash endurance is finite.
#
# Özellikler:
# - Selenium / Chromium / Flask YOK
# - HTTPS login + CSRF + sessionid
# - T3 KYS başvuru API'si
# - Değişiklik geçmişi
# - "Okundu" ve "Tümünü Okundu İşaretle"
# - Orijinal Flask dashboard'un arayüz/endpoint mantığı
# - Başvurular
# - Sistem Durumu
# - Flash üzerinde state
# - Wi-Fi / session / HTTP hata toleransı
#
# Gereken MicroPython modülleri:
#   network, socket, ujson, urequests
#
# ============================================================

import gc
import time
import random
import network
import socket
import ujson
import urequests
try:
    PermissionError
except NameError:
    class PermissionError(Exception):
        pass

try:
    import machine
except ImportError:
    machine = None

# ============================================================
# DAHİLİ RGB LED - PARAZİT/DENGELİ WS2812 SÜRÜCÜSÜ
# ============================================================
# ESP32-S3 DevKit v1.3 üzerindeki RGB LED GPIO48'dedir.
# NeoPixel yerine SPI kodlaması kullanıyoruz; bu yöntem kullanıcının
# kart üzerinde doğruladığı daha kararlı sürücüdür.
#
# Güç hattındaki paraziti azaltmak için:
# - CPU 240 MHz'de sabitlenir.
# - LED parlaklığı 1/12 ile sınırlandırılır.
# - LED yalnızca durum değiştiğinde yazılır; sürekli veri gönderilmez.
# - WS2812 reset/latch süresi korunur.
# - Wi-Fi KAPATILMAZ; monitorün bağlantısı bozulmasın diye LED
#   yazımı Wi-Fi bağlantısını kesmeden yapılır.

LED_PIN = 48
LED_SCK_PIN = 39
LED_BRIGHTNESS_DIV = 12
LED_SPI_BAUDRATE = 3200000
LED_SPI = None
LED_LAST_COLOR = None
LED_INITIALIZED = False

if machine is not None:
    try:
        machine.freq(240000000)
    except Exception:
        pass

    try:
        LED_SPI = machine.SPI(
            1,
            baudrate=LED_SPI_BAUDRATE,
            sck=machine.Pin(LED_SCK_PIN),
            mosi=machine.Pin(LED_PIN),
        )
        LED_INITIALIZED = True
    except Exception:
        LED_SPI = None
        LED_INITIALIZED = False


def _led_send_spi(r, g, b, force=False):
    global LED_LAST_COLOR

    if not LED_INITIALIZED or LED_SPI is None:
        return

    # Güç tüketimini ve dolayısıyla LED/Wi-Fi hattındaki ani
    # akım değişimini azalt.
    r = max(0, min(255, int(r))) // LED_BRIGHTNESS_DIV
    g = max(0, min(255, int(g))) // LED_BRIGHTNESS_DIV
    b = max(0, min(255, int(b))) // LED_BRIGHTNESS_DIV

    color = (r, g, b)
    if (not force) and color == LED_LAST_COLOR:
        return

    buf = bytearray()
    for value in (g, r, b):
        for bit in range(7, -1, -1):
            buf.append(0b1110 if ((value >> bit) & 1) else 0b1000)

    reset = bytearray(50)

    try:
        LED_SPI.write(reset)
        LED_SPI.write(buf)
        LED_SPI.write(reset)
        # WS2812 latch/reset süresi.
        time.sleep_us(80)
        LED_LAST_COLOR = color
    except Exception as exc:
        log("RGB LED SPI yazma hatasi: {}".format(exc))


def led_set(r, g, b):
    _led_send_spi(r, g, b)

def led_off():
    # Okunmamış değişiklik varsa alarm LED'i ASLA söndürülmez.
    if _unread_changes > 0:
        led_set(0, 255, 0)
    else:
        led_set(0, 0, 0)

def led_set_error(active):
    # Alarm en yüksek önceliktir.
    if _unread_changes > 0:
        led_set(0, 255, 0)
    elif active:
        led_set(255, 0, 0)
    else:
        led_off()

def led_set_login(active):
    if _unread_changes > 0:
        led_set(0, 255, 0)
    elif active:
        led_set(255, 255, 0)
    else:
        led_off()

def led_set_check(active):
    if _unread_changes > 0:
        led_set(0, 255, 0)
    elif active:
        led_set(0, 0, 255)
    else:
        led_off()

def led_start_alert():
    _led_send_spi(0, 255, 0, force=True)

def led_refresh_alert():
    if _unread_changes > 0:
        _led_send_spi(0, 255, 0, force=True)

def led_stop_alert():
    # Sayaç sıfırlanmadan alarmı söndürme.
    if _unread_changes > 0:
        led_set(0, 255, 0)
    else:
        led_set(0, 0, 0)


def led_init():
    if not LED_INITIALIZED:
        log("RGB LED SPI baslatilamadi.")
        return
    led_off()
    log("RGB LED hazir - SPI {} baud / parlaklik 1/{} / GPIO{}".format(
        LED_SPI_BAUDRATE, LED_BRIGHTNESS_DIV, LED_PIN
    ))

# ============================================================
# AYARLAR
# ============================================================

# Wi-Fi profilleri: her SSID kendi parolasıyla saklanır.
# WIFI_PROFILES = [{"ssid": "EvWiFi", "password": "12345678"}]
WIFI_PROFILES = [
{"ssid": "Your_SSID", "password": "password"},
{"ssid": "Your_SSID2", "password": "password2"}                
]

T3_EMAIL = "example@gmail.com"
T3_PASSWORD = "password"

BASE_URL = "https://t3kys.com"
T3_URL = BASE_URL + "/tr/applications/"
LOGIN_URL = BASE_URL + "/en/accounts/login/?next=/en/"
APPLICATIONS_API = (
    BASE_URL
    + "/tr/mainpage/table-api/my-applications/v2/"
    + "?format=datatables"
)

# Polling ayarları.
CHECK_INTERVAL = 1200
MIN_CHECK_INTERVAL = 840
MAX_CHECK_INTERVAL = 3000
JITTER_SECONDS = 120
TRT_OFFSET_SECONDS = 3 * 60 * 60
PAGE_SIZE = 5
HTTP_TIMEOUT = 30

SETTINGS_FILE = "t3_settings.json"
STATE_FILE = "t3_state.json"
CHANGES_FILE = "t3_changes.json"
SYSTEM_FILE = "t3_system.json"
COMPETITIONS_FILE = "t3_competitions.json"
APPLICATIONS_FILE = "t3_applications.json"
COMPETITION_DETAILS_FILE = "t3_competition_details.json"
CERTIFICATES_FILE = "t3_certificates.json"

WEB_PORT = 80

# Flash üzerinde en fazla değişiklik geçmişi.
MAX_CHANGES = 500

TRACKED_FIELDS = (
    ("status", "Durum"),
    ("is_eliminated", "Eliminasyon durumu"),
    ("certificate_url", "Sertifika"),
    ("form_link", "Form"),
    ("movements", "Başvuru hareketleri"),
)

# ============================================================
# GLOBAL DURUM
# ============================================================

monitor_state = {
    "running": False,
    "waiting_login": True,
    "last_check": None,
    "next_check": None,
    "next_check_delay": CHECK_INTERVAL,
    "last_error": None,
    "total_applications": 0,
    "total_programs": 0,
    "first_scan_completed": False,
    "started_at": None,
    "force_check": False,
    "force_reconnect": False,
    "force_relogin": False,
    "stats": {
        "success": 0,
        "fail": 0,
        "appeal": 0,
        "evaluation": 0,
        "winner": 0,
        "applied": 0,
    },
}

settings = {
    "wifi_profiles": WIFI_PROFILES,
    "t3_email": T3_EMAIL,
    "t3_password": T3_PASSWORD,
    "check_interval": CHECK_INTERVAL,
    "min_check_interval": MIN_CHECK_INTERVAL,
    "max_check_interval": MAX_CHECK_INTERVAL,
}

http_session = None
web_server = None

_unread_changes = 0

# ============================================================
# LOG / RAM
# ============================================================

def log(text):
    print("[T3] " + str(text))

def free_ram():
    gc.collect()
    try:
        return gc.mem_free()
    except Exception:
        return -1

# ============================================================
# JSON / FLASH
# ============================================================

def load_json(filename, default):
    try:
        with open(filename, "r") as f:
            return ujson.load(f)
    except Exception:
        return default

def save_json(filename, data):
    # ujson.dump doğrudan dosyaya yazar; dumps() ile büyük bir
    # JSON string'i RAM'de ayrıca oluşturmuyoruz.
    tmp = filename + ".tmp"

    gc.collect()

    try:
        with open(tmp, "w") as f:
            ujson.dump(data, f)

        gc.collect()

        try:
            import os
            try:
                os.remove(filename)
            except Exception:
                pass
            os.rename(tmp, filename)
        except Exception:
            # rename başarısızsa doğrudan hedefe yaz.
            with open(filename, "w") as f:
                ujson.dump(data, f)

            try:
                import os
                os.remove(tmp)
            except Exception:
                pass

    except Exception as exc:
        log("Flash yazma hatası {}: {}".format(filename, exc))

    gc.collect()

def normalize_settings(data):
    if not isinstance(data, dict):
        return

    profiles = data.get("wifi_profiles")
    if isinstance(profiles, list):
        clean_profiles = []
        for item in profiles:
            if not isinstance(item, dict):
                continue
            ssid = str(item.get("ssid", "")).strip()
            password = str(item.get("password", ""))
            if ssid:
                clean_profiles.append({
                    "ssid": ssid,
                    "password": password,
                })
        settings["wifi_profiles"] = clean_profiles

    if data.get("t3_email") is not None:
        settings["t3_email"] = str(data.get("t3_email")).strip()

    if data.get("t3_password") is not None:
        settings["t3_password"] = str(data.get("t3_password"))

    for key, lower, upper in (
        ("check_interval", 30, 86400),
        ("min_check_interval", 30, 86400),
        ("max_check_interval", 30, 86400),
    ):
        if key in data:
            try:
                settings[key] = max(
                    lower,
                    min(upper, int(data.get(key)))
                )
            except Exception:
                pass

    if settings["min_check_interval"] > settings["max_check_interval"]:
        (
            settings["min_check_interval"],
            settings["max_check_interval"],
        ) = (
            settings["max_check_interval"],
            settings["min_check_interval"],
        )

def load_settings():
    global WIFI_PROFILES
    global T3_EMAIL, T3_PASSWORD
    global CHECK_INTERVAL, MIN_CHECK_INTERVAL, MAX_CHECK_INTERVAL

    data = load_json(SETTINGS_FILE, {})
    normalize_settings(data)

    WIFI_PROFILES = settings.get("wifi_profiles", [])
    T3_EMAIL = settings.get("t3_email", "")
    T3_PASSWORD = settings.get("t3_password", "")
    CHECK_INTERVAL = int(settings.get("check_interval", CHECK_INTERVAL))
    MIN_CHECK_INTERVAL = int(
        settings.get("min_check_interval", MIN_CHECK_INTERVAL)
    )
    MAX_CHECK_INTERVAL = int(
        settings.get("max_check_interval", MAX_CHECK_INTERVAL)
    )

def save_settings():
    save_json(
        SETTINGS_FILE,
        {
            "wifi_profiles": settings.get("wifi_profiles", []),
            "t3_email": settings.get("t3_email", ""),
            "t3_password": settings.get("t3_password", ""),
            "check_interval": int(settings.get("check_interval", CHECK_INTERVAL)),
            "min_check_interval": int(
                settings.get("min_check_interval", MIN_CHECK_INTERVAL)
            ),
            "max_check_interval": int(
                settings.get("max_check_interval", MAX_CHECK_INTERVAL)
            ),
        },
    )

def apply_settings(data, immediate=True):
    global WIFI_PROFILES
    global T3_EMAIL, T3_PASSWORD
    global CHECK_INTERVAL, MIN_CHECK_INTERVAL, MAX_CHECK_INTERVAL
    global http_session

    old_wifi = WIFI_PROFILES
    old_email = T3_EMAIL
    old_password = T3_PASSWORD

    normalize_settings(data)

    WIFI_PROFILES = settings.get("wifi_profiles", [])
    T3_EMAIL = settings.get("t3_email", "")
    T3_PASSWORD = settings.get("t3_password", "")
    CHECK_INTERVAL = int(settings.get("check_interval", CHECK_INTERVAL))
    MIN_CHECK_INTERVAL = int(
        settings.get("min_check_interval", MIN_CHECK_INTERVAL)
    )
    MAX_CHECK_INTERVAL = int(
        settings.get("max_check_interval", MAX_CHECK_INTERVAL)
    )

    wifi_changed = old_wifi != WIFI_PROFILES
    credentials_changed = (
        old_email != T3_EMAIL or old_password != T3_PASSWORD
    )

    save_settings()

    if credentials_changed:
        http_session = None
        monitor_state["force_relogin"] = True

    if wifi_changed:
        monitor_state["force_reconnect"] = True

    if immediate:
        monitor_state["force_check"] = True

    monitor_state["next_check"] = time.time()
    monitor_state["next_check_delay"] = 0
    save_monitor_state()

    return {
        "ok": True,
        "wifi_changed": wifi_changed,
        "credentials_changed": credentials_changed,
        "force_check": immediate,
    }

def rebuild_cached_classification():
    """Flash'taki başvuruları güncel sınıflandırmayla check beklemeden yeniler."""
    try:
        cached = load_json(APPLICATIONS_FILE, [])
        if not isinstance(cached, list):
            cached = []

        rebuilt = []
        for item in cached:
            if not isinstance(item, dict):
                continue
            program = clean_html(item.get("program"))
            status = clean_html(item.get("status"))
            movements = clean_html(item.get("movements"))
            # Eski status_key/status_label kesinlikle kaynak alınmaz;
            # yalnızca ham program/status/movements metninden yeniden hesaplanır.
            key, year, icon, label = classify_competition(program, status, movements)
            item["status_key"] = key
            item["status_icon"] = icon
            item["status_label"] = label
            item["competition_year"] = year
            rebuilt.append(item)

        if rebuilt:
            save_json(APPLICATIONS_FILE, rebuilt)

        competitions = build_competitions(rebuilt)
        monitor_state["stats"] = build_statistics(competitions)
        monitor_state["total_programs"] = len(competitions)
        monitor_state["total_applications"] = len(rebuilt)
        save_json(COMPETITIONS_FILE, competitions)
        save_monitor_state()

        del competitions
        del rebuilt
        del cached
        gc.collect()
    except Exception as exc:
        log("Önbellek sınıflandırma yenileme hatası: {}".format(exc))

def load_all_state():
    global monitor_state

    load_settings()

    saved = load_json(SYSTEM_FILE, {})
    if isinstance(saved, dict):
        for key in monitor_state:
            if key in saved:
                monitor_state[key] = saved[key]

    # Sınıflandırma ana akışta NTP sonrasında tek kez yenilenir.
    # Açılışta burada Flash'a tekrar yazmıyoruz.

_last_saved_system_data = None

def save_monitor_state(force=False):
    global _last_saved_system_data
    
    # Sürekli değişen (zaman, timestamp vb.) alanlar yerine 
    # sadece yeniden başlatmada kalıcı olmasını istediğimiz kritik alanları karşılaştırıyoruz.
    current_data = {
        "stats": monitor_state.get("stats"),
        "total_app": monitor_state.get("total_applications"),
        "total_prog": monitor_state.get("total_programs"),
        "err": str(monitor_state.get("last_error")),
        "waiting": monitor_state.get("waiting_login")
    }
    
    # Veriler aynıysa ve zorunlu bir kayıt istenmediyse Flash'a yazmayı atla
    if not force and _last_saved_system_data == current_data:
        return
        
    save_json(SYSTEM_FILE, monitor_state)
    _last_saved_system_data = current_data

# ============================================================
# HTTP SESSION
# ============================================================

class T3Session:

    def __init__(self):
        self.cookies = {}
        self.logged_in = False

    def clear(self):
        self.cookies = {}
        self.logged_in = False

    def cookie_header(self):
        if not self.cookies:
            return ""

        return "; ".join(
            "{}={}".format(k, v)
            for k, v in self.cookies.items()
        )

    def update_cookies(self, response):
        try:
            value = response.headers.get("Set-Cookie")
        except Exception:
            value = None

        if not value:
            return

        # Python/MicroPython HTTP header'larında genellikle tek Set-Cookie
        # veya virgülle ayrılmış değer bulunur.
        chunks = value.split(",")

        for chunk in chunks:
            first = chunk.split(";", 1)[0].strip()

            if "=" not in first:
                continue

            name, val = first.split("=", 1)

            if name:
                self.cookies[name.strip()] = val.strip()

    def headers(self, extra=None):
            h = {
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Mobile/15E148 Safari/604.1",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
                "Connection": "close", # Tarpit (askıda kalma) engellemek için
                "Upgrade-Insecure-Requests": "1"
            }

            cookie = self.cookie_header()

            if cookie:
                h["Cookie"] = cookie

            if extra:
                for k, v in extra.items():
                    h[k] = v

            return h

def waf_detected(response):
    # Eğer dönen durum kodu WAF bloklarına ait (202 veya 403) değilse,
    # body'yi (response.text) gereksiz yere okuyup RAM'i şişirmesini engelliyoruz.
    if getattr(response, "status_code", 200) not in (202, 403):
        return False

    try:
        body = response.text.lower()
    except Exception:
        return False

    markers = (
        "challenge.js",
        "awswaf",
        "aws-waf-token",
        "awswaf-captcha",
    )

    return any(x in body for x in markers)

def extract_csrf(html):
    markers = (
        'name="csrfmiddlewaretoken"',
        "name='csrfmiddlewaretoken'",
    )

    for marker in markers:
        pos = html.find(marker)

        if pos < 0:
            continue

        value_pos = html.find("value=", pos)

        if value_pos < 0:
            continue

        p = value_pos + 6

        while p < len(html) and html[p] in " \t":
            p += 1

        if p >= len(html):
            continue

        quote = html[p]

        if quote not in ("'", '"'):
            continue

        end = html.find(quote, p + 1)

        if end > p:
            return html[p + 1:end]

    return None

def url_encode(value):
    # application/x-www-form-urlencoded için küçük encoder.
    safe = (
        "abcdefghijklmnopqrstuvwxyz"
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        "0123456789"
        "-_.~"
    )

    out = []

    for ch in str(value):
        if ch in safe:
            out.append(ch)
        elif ch == " ":
            out.append("+")
        else:
            for byte in ch.encode("utf-8"):
                out.append("%{:02X}".format(byte))

    return "".join(out)

def t3_login():
    global http_session

    led_set_error(False)
    led_set_login(True)

    # Login sırasında geçici socket/TLS hataları olabilir. Bunları burada
    # kontrollü olarak yeniden deniyoruz; ana monitor döngüsünü gereksiz yere
    # Wi-Fi tarafına geri döndürmüyoruz.
    MAX_LOGIN_ATTEMPTS = 3

    try:
        import ssl
    except ImportError:
        import ussl as ssl

    last_error = None

    for attempt in range(1, MAX_LOGIN_ATTEMPTS + 1):
        session = T3Session()

        html = None
        csrf = None
        payload = None
        s = None
        addr = None

        try:
            gc.collect()
            log(
                "Login başlatılıyor ({}/{})...".format(
                    attempt,
                    MAX_LOGIN_ATTEMPTS
                )
            )

            # --------------------------------------------------------
            # 1) Login sayfası + CSRF + ilk cookie'ler
            # --------------------------------------------------------
            response = None
            try:
                response = urequests.get(
                    LOGIN_URL,
                    headers=session.headers(),
                    timeout=HTTP_TIMEOUT
                )

                session.update_cookies(response)

                if waf_detected(response):
                    raise RuntimeError(
                        "Sunucu WAF challenge döndürdü."
                    )

                if response.status_code != 200:
                    raise RuntimeError(
                        "Login GET HTTP {}".format(
                            response.status_code
                        )
                    )

                html = response.text

            finally:
                if response is not None:
                    try:
                        response.close()
                    except Exception:
                        pass
                response = None

            csrf = extract_csrf(html)

            # TLS başlamadan önce büyük login HTML'ini bırak.
            del html
            html = None
            gc.collect()

            if not csrf:
                raise RuntimeError("CSRF token bulunamadı.")

            payload = (
                "csrfmiddlewaretoken={}"
                "&login={}"
                "&password={}"
            ).format(
                url_encode(csrf),
                url_encode(T3_EMAIL),
                url_encode(T3_PASSWORD),
            )

            del csrf
            csrf = None
            gc.collect()

            # --------------------------------------------------------
            # 2) HTTPS POST / Set-Cookie
            # --------------------------------------------------------
            log("Login POST gönderiliyor...")

            try:
                proto, dummy, host, path = LOGIN_URL.split("/", 3)
            except ValueError:
                proto, dummy, host = LOGIN_URL.split("/", 2)
                path = ""

            addr = socket.getaddrinfo(host, 443)[0][-1]
            s = socket.socket()
            s.settimeout(HTTP_TIMEOUT)

            try:
                gc.collect()
                s.connect(addr)

                try:
                    s = ssl.wrap_socket(
                        s,
                        server_hostname=host
                    )
                except TypeError:
                    s = ssl.wrap_socket(s)

                headers = session.headers({
                    "Referer": LOGIN_URL,
                    "Origin": BASE_URL,
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Content-Length": str(len(payload)),
                })

                # Orijinal çalışan yapıya yakın: bytes parçaları oluşturup
                # tek req_data olarak gönderiyoruz.
                req_lines = [
                    b"POST /%s HTTP/1.0" % path.encode("utf-8"),
                    b"Host: %s" % host.encode("utf-8"),
                ]

                for k, v in headers.items():
                    req_lines.append(
                        b"%s: %s" % (
                            k.encode("utf-8"),
                            v.encode("utf-8")
                        )
                    )

                req_lines.append(b"")
                req_lines.append(payload.encode("utf-8"))

                req_data = b"\r\n".join(req_lines)
                s.write(req_data)

                del req_lines
                del req_data
                del headers
                del payload
                payload = None
                gc.collect()

                # HTTP status satırı
                status_line = s.readline()
                status_parts = status_line.split(None, 2)

                if len(status_parts) < 2:
                    raise RuntimeError(
                        "Geçersiz HTTP yanıtı (POST)."
                    )

                status_code = int(status_parts[1])

                if status_code in (202, 403):
                    raise RuntimeError(
                        "Login reddedildi: HTTP {}".format(
                            status_code
                        )
                    )

                if status_code not in (200, 301, 302, 303):
                    raise RuntimeError(
                        "Login POST HTTP {}".format(
                            status_code
                        )
                    )

                # ------------------------------------------------
                # HTTP header'larını oku ve bütün Set-Cookie
                # başlıklarını case-insensitive yakala.
                # ------------------------------------------------
                while True:
                    line = s.readline()

                    if not line or line == b"\r\n":
                        break

                    try:
                        line_str = line.decode(
                            "utf-8",
                            "ignore"
                        ).strip()

                        if ":" in line_str:
                            header_name, header_value = line_str.split(
                                ":",
                                1
                            )

                            if header_name.strip().lower() == "set-cookie":
                                first = header_value.split(
                                    ";",
                                    1
                                )[0].strip()

                                if "=" in first:
                                    name, cval = first.split("=", 1)
                                    name = name.strip()
                                    cval = cval.strip()

                                    if name:
                                        session.cookies[name] = cval

                        del line_str
                    except Exception:
                        pass

            finally:
                if s is not None:
                    try:
                        s.close()
                    except Exception:
                        pass
                s = None

            addr = None
            gc.collect()

            # Bazı oturumlarda sessionid GET cevabında zaten bulunabilir;
            # POST cevabında ayrıca set edilmişse yukarıdaki parser bunu
            # ezmeden güncellemiştir.
            if "sessionid" not in session.cookies:
                raise RuntimeError(
                    "Login başarısız; sessionid alınamadı."
                )

            session.logged_in = True
            http_session = session

            log("HTTP login başarılı.")
            log("RAM: {} bytes".format(free_ram()))
            led_set_login(False)
            return

        except (OSError, RuntimeError) as exc:
            last_error = exc

            # WAF / 401 benzeri mantıksal redleri de üst döngüye bırakıyoruz;
            # fakat geçici socket hatalarında tekrar denemek faydalıdır.
            retryable = isinstance(exc, OSError)

            text = str(exc).upper()
            if (
                "ECONNABORTED" in text
                or "ETIMEDOUT" in text
                or "ECONNRESET" in text
                or "EPIPE" in text
                or "EHOSTUNREACH" in text
            ):
                retryable = True

            log(
                "Login hatası [{}] deneme {}/{}: {}".format(
                    type(exc).__name__,
                    attempt,
                    MAX_LOGIN_ATTEMPTS,
                    exc
                )
            )

            if attempt >= MAX_LOGIN_ATTEMPTS or not retryable:
                raise

            time.sleep_ms(500 * attempt)

        finally:
            if html is not None:
                del html

            if csrf is not None:
                del csrf

            if payload is not None:
                del payload

            if s is not None:
                try:
                    s.close()
                except Exception:
                    pass

            gc.collect()

    led_set_login(False)
    led_set_error(True)
    raise RuntimeError(
        "Login başarısız: {}".format(last_error)
    )

# ============================================================
# T3 API
# ============================================================

def _remove_html_tags(text):
    out=[]
    inside=False
    i=0
    n=len(text)
    while i<n:
        ch=text[i]
        if ch=="<":
            inside=True
        elif ch==">" and inside:
            inside=False
        elif not inside:
            out.append(ch)
        i+=1
    return "".join(out)


def _collapse_spaces(text):
    out=[]
    in_space=False
    for ch in text:
        if ch in " \t\r\n\f":
            if not in_space:
                out.append(" ")
                in_space=True
        else:
            out.append(ch)
            in_space=False
    return "".join(out).strip()


def clean_html(value):
    if value is None:
        return ""
    text = str(value)
    text = _remove_html_tags(text)
    text = text.replace("&nbsp;", " ")
    text = text.replace("&amp;", "&")
    text = text.replace("&lt;", "<")
    text = text.replace("&gt;", ">")
    text = text.replace("&quot;", '"')
    text = text.replace("&#039;", "'")
    return _collapse_spaces(text)

def iter_application_rows():
    global http_session

    if http_session is None or not http_session.logged_in:
        raise RuntimeError("HTTP oturumu aktif değil.")

    start = 0
    draw = 1
    seen_ids = set()
    total_seen = 0

    while True:
        url = (
            APPLICATIONS_API
            + "&draw={}"
            + "&start={}"
            + "&length={}"
            + "&search="
        ).format(
            draw,
            start,
            PAGE_SIZE
        )

        response = None
        raw = None
        data = None

        try:
            gc.collect()

            response = urequests.get(
                url,
                headers=http_session.headers({
                    "Referer": T3_URL,
                    "X-Requested-With": "XMLHttpRequest",
                    "Accept": "application/json, text/plain, */*",
                }),
                timeout=HTTP_TIMEOUT
            )

            if waf_detected(response):
                raise RuntimeError(
                    "Başvuru API'sinde WAF challenge."
                )

            if response.status_code in (401, 403):
                raise PermissionError(
                    "API oturumu reddetti: HTTP {}".format(
                        response.status_code
                    )
                )

            if response.status_code != 200:
                raise RuntimeError(
                    "Başvuru API HTTP {}".format(
                        response.status_code
                    )
                )

            # response nesnesini kapatmadan önce gövdeyi alıyoruz.
            # PAGE_SIZE küçük olduğu için anlık JSON bloğu sınırlı kalıyor.
            raw = response.text

        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass
            response = None

        try:
            # Büyük HTML/response nesnesi artık yok; parse sırasında
            # yalnızca raw + küçük sayfalık Python objeleri canlı.
            data = ujson.loads(raw)
        finally:
            del raw
            raw = None

        rows = data.get("data", [])

        if not isinstance(rows, list):
            del data
            data = None
            raise RuntimeError("API data alanı liste değil.")

        row_count = len(rows)

        total = data.get(
            "recordsFiltered",
            data.get(
                "recordsTotal",
                total_seen + row_count
            )
        )

        try:
            total = int(total)
        except Exception:
            total = total_seen + row_count

        # Her seferinde yalnızca mevcut sayfadaki kayıtlar generator
        # üzerinden dışarı veriliyor; tüm API cevabı 'records' listesinde
        # birikmiyor.
        added_in_page = 0
        for record in rows:
            record_id = record.get("id")

            if record_id is None:
                continue

            key = str(record_id)

            if key in seen_ids:
                continue

            seen_ids.add(key)
            total_seen += 1
            added_in_page += 1
            yield record

        del rows
        del data
        gc.collect()

        if (
            row_count == 0
            or total_seen >= total
            or row_count < PAGE_SIZE
            or draw >= 50
            or (row_count > 0 and added_in_page == 0)
        ):
            break

        start += row_count
        draw += 1

        # Sunucuyu gereksiz yere sıkıştırmadan bir sonraki sayfaya geç.
        time.sleep_ms(150)

        del url
        gc.collect()

    del seen_ids
    gc.collect()

def get_applications():
    # Geriye dönük uyumluluk için bırakıldı.
    # Normal akış iter_application_rows() kullanır.
    records = []

    for record in iter_application_rows():
        records.append(record)

    return records

# STATE / DEĞİŞİKLİK
# ============================================================



def extract_url(value):
    """Düz URL veya HTML içinden en olası sertifika URL'sini çıkarır."""
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""

    if text.startswith("http://") or text.startswith("https://"):
        return text

    lower = text.lower()
    candidates = []
    for marker in (
        'href="', "href='", 'href = "', "href = '",
        'src="', "src='", 'src = "', "src = '",
    ):
        pos = 0
        while True:
            found = lower.find(marker, pos)
            if found < 0:
                break
            start_pos = found + len(marker)
            quote = marker[-1]
            end_pos = text.find(quote, start_pos)
            if end_pos < 0:
                break
            url = text[start_pos:end_pos].strip()
            if url.startswith("//"):
                url = "https:" + url
            elif url.startswith("/"):
                url = BASE_URL + url
            if url.startswith("http://") or url.startswith("https://"):
                candidates.append(url)
            pos = end_pos + 1

    if not candidates:
        return ""

    # PDF/certificate/download bağlantılarını login/home gibi genel linklerden önce seç.
    best = candidates[0]
    best_score = -1
    for url in candidates:
        u = url.lower()
        score = 0
        if ".pdf" in u:
            score += 100
        if "certificate" in u or "sertifika" in u:
            score += 60
        if "download" in u or "media" in u or "file" in u:
            score += 30
        if "login" in u or "accounts/login" in u:
            score -= 100
        if score > best_score:
            best_score = score
            best = url
    return best


def make_state(record):
    # STATE_FILE yalnızca karşılaştırma için gereken alanları tutar.
    # created_at / applicant_or_team gibi dashboard alanları burada
    # gereksiz yer işgali yapmaz.
    return {
        "id": str(record.get("id", "")),
        "program": clean_html(record.get("program")),
        "status": clean_html(record.get("status")),
        "is_eliminated": record.get("is_eliminated"),
        "certificate_url": extract_url(record.get("certificate_url")),
        "form_link": clean_html(
            record.get("form_link")
        ),
        "movements": clean_html(
            record.get("movements")
        ),
    }

def compare_states(old, new):
    changes = []

    for field, label in TRACKED_FIELDS:
        old_value = old.get(field)
        new_value = new.get(field)

        if old_value != new_value:
            changes.append({
                "field": field,
                "label": label,
                "old": old_value,
                "new": new_value,
            })

    return changes

def load_changes():
    data = load_json(CHANGES_FILE, [])

    if isinstance(data, list):
        return data

    return []

def save_changes(changes):
    if len(changes) > MAX_CHANGES:
        # Son MAX_CHANGES kayıt kalsın.
        del changes[:-MAX_CHANGES]

    save_json(CHANGES_FILE, changes)

def add_change(record, field_changes):
    # Flash'a bu aşamada yazmıyoruz. Tüm yeni değişiklikler
    # perform_check() sonunda tek seferde kaydediliyor.
    return {
        "id": "{}_{}".format(
            record.get("id"),
            time.ticks_ms()
        ),
        "timestamp": time.time(),
        "read": False,
        "record_id": str(record.get("id")),
        "program": clean_html(record.get("program")),
        "changes": field_changes,
    }

def extract_competition_year(program):
    text = str(program or "")
    i=0
    while i+3 < len(text):
        if ("0" <= text[i] <= "9" and
            "0" <= text[i+1] <= "9" and
            "0" <= text[i+2] <= "9" and
            "0" <= text[i+3] <= "9"):
            try:
                year=int(text[i:i+4])
                if 2000 <= year <= 2099:
                    return year
            except Exception:
                pass
        i+=1
    return None

def normalize_status_text(value):
    text = clean_html(value)

    replacements = (
        ("İ", "I"),
        ("ı", "i"),
        ("ş", "s"),
        ("Ş", "s"),
        ("ç", "c"),
        ("Ç", "c"),
        ("ö", "o"),
        ("Ö", "o"),
        ("ü", "u"),
        ("Ü", "u"),
        ("ğ", "g"),
        ("Ğ", "g"),
    )

    for old_char, new_char in replacements:
        text = text.replace(old_char, new_char)

    return text.lower()

def classify_competition(program, status, movements):
    current_year = time.localtime(time.time())[0]
    year = extract_competition_year(program)
    if year is None:
        year = extract_competition_year(movements)

    joined = normalize_status_text(str(status or "") + " " + str(movements or ""))

    # "BAŞVURU ALINDI" özel etikettir; bunun dışında sınıflandırma sonuç odaklıdır.
    has_applied = (
        "basvuru alindi" in joined
        or "basvurunuz alindi" in joined
        or "basvurunuz alinmistir" in joined
        or "basvuru alinmistir" in joined
        or "basvuru onaylandi" in joined
        or "application received" in joined
        or "received application" in joined
    )

    # Kesin öncelik: İtiraz > Kazanan > Başarılı > Başarısız > Başvuru Alındı > Değerlendirme
    if "itiraz" in joined or "appeal" in joined:
        return "appeal", year, "⚖", status or "İtiraz"

    if (
        "kazanan" in joined
        or "winner" in joined
        or "derece" in joined
        or "sampiyon" in joined
    ):
        return "winner", year, "🏆", status or "Kazanan"

    if (
        "basarili" in joined
        or "finalist" in joined
        or "success" in joined
    ):
        return "success", year, "✓", status or "Başarılı"

    if (
        "elen" in joined
        or "elendi" in joined
        or "basarisiz" in joined
        or "failed" in joined
        or "reject" in joined
    ):
        return "fail", year, "✕", status or "Başarısız"

    # "BAŞVURU ALINDI" sonuçsuz ama açık bir durumdur; yılından bağımsız
    # olarak ayrı beyaz bilet kategorisinde tutulur.
    if has_applied:
        return "applied", year, "🎫", status or "BAŞVURU ALINDI"

    # Sonuçsuz eski yıl kayıtları artık değerlendirme değil Başarısızdır.
    # Bu kontrol özellikle "Final Değerlendirme Durumu" gibi metinlerde
    # belirleyicidir: metinde değerlendirme geçse bile yıl eskiyse değerlendirme değildir.
    if year is not None and year != current_year:
        return "fail", year, "✕", status or "Başarısız"

    return "evaluation", year, "⌛", status or "Değerlendirme"

def build_statistics(competitions):
    stats = {
        "success": 0,
        "fail": 0,
        "appeal": 0,
        "evaluation": 0,
        "winner": 0,
        "applied": 0,
    }

    for item in competitions:
        key = item.get("status_key", "evaluation")
        if key in stats:
            stats[key] += 1

    return stats

def build_competitions(records):
    result = {}

    for record in records:
        program = clean_html(record.get("program"))

        if not program:
            continue

        if program not in result:
            result[program] = {
                "program": program,
                "ids": [],
                "statuses": [],
                "count": 0,
                "last_change": None,
                "status_key": "evaluation",
                "status_icon": "⌛",
                "status_label": "Değerlendirme",
                "competition_year": None,
            }

        item = result[program]

        record_id = str(record.get("id", ""))

        if record_id and record_id not in item["ids"]:
            item["ids"].append(record_id)

        status = clean_html(record.get("status"))
        movements = clean_html(record.get("movements"))
        status_key, competition_year, status_icon, status_label = (
            classify_competition(
                program,
                status,
                movements
            )
        )

        if status and status not in item["statuses"]:
            item["statuses"].append(status)

        priority = {
            "appeal": 6,
            "winner": 5,
            "success": 4,
            "fail": 3,
            "applied": 2,
            "evaluation": 1,
        }

        current_key = item.get("status_key", "evaluation")
        if priority.get(status_key, 1) >= priority.get(current_key, 1):
            item["status_key"] = status_key
            item["status_icon"] = status_icon
            item["status_label"] = status_label

        item["competition_year"] = competition_year
        item["count"] += 1

    values = list(result.values())

    # casefold MicroPython sürümüne göre olmayabilir.
    values.sort(
        key=lambda x: x["program"].lower()
    )

    return values

def strip_html_text(value):
    if value is None:
        return ""
    text = str(value)
    # Script/style bloklarını basit marker taramasıyla at.
    for tag in ("script", "style"):
        lower=text.lower()
        pos=0
        while True:
            a=lower.find("<"+tag, pos)
            if a<0:
                break
            b=lower.find("</"+tag+">", a)
            if b<0:
                text=text[:a]
                break
            text=text[:a]+text[b+len(tag)+3:]
            lower=text.lower()
            pos=a
    return clean_html(text)

def _html_tag_text(fragment):
    """Basit HTML metin temizleme; MicroPython uyumlu."""
    return strip_html_text(fragment or "")


def _find_all_positions(text, marker, start_pos=0):
    """str.find() kullanarak marker konumlarını döndürür."""
    positions = []
    pos = max(0, int(start_pos))
    marker_len = len(marker)
    if marker_len <= 0:
        return positions

    while pos < len(text):
        found = text.find(marker, pos)
        if found < 0:
            break
        positions.append(found)
        pos = found + marker_len

    return positions


def _extract_first_after(block, marker, end_marker=""):
    """Marker sonrasındaki ilk alanı çıkarır."""
    pos = block.find(marker)
    if pos < 0:
        return ""
    pos += len(marker)

    if end_marker:
        end = block.find(end_marker, pos)
        if end < 0:
            return ""
        return block[pos:end]

    return block[pos:]


def _extract_first_tag_content_after(block, marker):
    """Marker sonrasındaki ilk >...< içeriğini çıkarır."""
    pos = block.find(marker)
    if pos < 0:
        return ""

    gt = block.find(">", pos)
    if gt < 0:
        return ""

    lt = block.find("<", gt + 1)
    if lt < 0:
        return ""

    return strip_html_text(block[gt + 1:lt])


def _find_attr_target_ids(block, attr_name="data-bs-target"):
    """HTML blokundan #id hedeflerini sadece str.find ile çıkarır."""
    result = []
    pos = 0
    marker = attr_name + '="'
    marker2 = attr_name + "='"
    while True:
        p1 = block.find(marker, pos)
        p2 = block.find(marker2, pos)
        if p1 < 0 and p2 < 0:
            break
        if p1 < 0:
            p = p2
            quote = "'"
            advance = len(marker2)
        elif p2 < 0 or p1 < p2:
            p = p1
            quote = '"'
            advance = len(marker)
        else:
            p = p2
            quote = "'"
            advance = len(marker2)
        value_start = p + advance
        value_end = block.find(quote, value_start)
        if value_end < 0:
            break
        value = block[value_start:value_end]
        if value.startswith("#"):
            value = value[1:]
        if value and value not in result:
            result.append(value)
        pos = value_end + 1
    return result


def _extract_div_by_id(html, element_id):
    """Belirli id'ye sahip DIV'i iç içe DIV derinliğiyle çıkarır."""
    if not element_id:
        return ""

    marker1 = 'id="' + element_id + '"'
    marker2 = "id='" + element_id + "'"
    p1 = html.find(marker1)
    p2 = html.find(marker2)
    if p1 < 0 and p2 < 0:
        return ""
    id_pos = p1 if p2 < 0 or (p1 >= 0 and p1 < p2) else p2
    div_start = html.rfind("<div", 0, id_pos)
    if div_start < 0:
        return ""

    pos = div_start
    depth = 0
    while pos < len(html):
        open_pos = html.find("<div", pos)
        close_pos = html.find("</div", pos)
        if close_pos < 0:
            return ""
        if open_pos >= 0 and open_pos < close_pos:
            depth += 1
            gt = html.find(">", open_pos)
            if gt < 0:
                return ""
            pos = gt + 1
        else:
            depth -= 1
            gt = html.find(">", close_pos)
            if gt < 0:
                gt = close_pos + 6
            pos = gt + 1
            if depth == 0:
                return html[div_start:pos]
    return ""


def _extract_first_div_class(fragment, class_token):
    marker1 = 'class="' + class_token
    marker2 = "class='" + class_token
    p1 = fragment.find(marker1)
    p2 = fragment.find(marker2)
    if p1 < 0 and p2 < 0:
        return ""
    p = p1 if p2 < 0 or (p1 >= 0 and p1 < p2) else p2
    div_start = fragment.rfind("<div", 0, p)
    if div_start < 0:
        return ""
    return _extract_div_from_pos(fragment, div_start)


def _extract_div_from_pos(html, div_start):
    pos = div_start
    depth = 0
    while pos < len(html):
        open_pos = html.find("<div", pos)
        close_pos = html.find("</div", pos)
        if close_pos < 0:
            return ""
        if open_pos >= 0 and open_pos < close_pos:
            depth += 1
            gt = html.find(">", open_pos)
            if gt < 0:
                return ""
            pos = gt + 1
        else:
            depth -= 1
            gt = html.find(">", close_pos)
            if gt < 0:
                gt = close_pos + 6
            pos = gt + 1
            if depth == 0:
                return html[div_start:pos]
    return ""


def _extract_all_divs_by_class(fragment, class_token):
    """class token içeren DIV bloklarını MicroPython uyumlu şekilde çıkarır."""
    result = []
    search = 0
    while True:
        marker1 = 'class="' + class_token
        marker2 = "class='" + class_token
        p1 = fragment.find(marker1, search)
        p2 = fragment.find(marker2, search)
        if p1 < 0 and p2 < 0:
            break
        p = p1 if p2 < 0 or (p1 >= 0 and p1 < p2) else p2
        div_start = fragment.rfind("<div", 0, p)
        if div_start < 0:
            break
        block = _extract_div_from_pos(fragment, div_start)
        if not block:
            break
        result.append(block)
        search = div_start + len(block)
    return result


def _extract_inner_text_after(fragment, marker):
    p = fragment.find(marker)
    if p < 0:
        return ""
    gt = fragment.find(">", p)
    if gt < 0:
        return ""
    lt = fragment.find("<", gt + 1)
    if lt < 0:
        return ""
    return strip_html_text(fragment[gt + 1:lt])


def _extract_numeric_token(text):
    text=str(text or "")
    i=0
    while i < len(text):
        if "0" <= text[i] <= "9":
            j=i
            while j < len(text) and "0" <= text[j] <= "9":
                j+=1
            if j < len(text) and text[j] in ".,":
                k=j+1
                if k < len(text) and "0" <= text[k] <= "9":
                    while k < len(text) and "0" <= text[k] <= "9":
                        k+=1
                    return text[i:k]
            token=text[i:j]
            if token:
                return token
        i+=1
    return None


def _extract_first_tag_block_after(fragment, class_token, start_pos=0):
    # class tokenu içeren ilk div/span/p bloğunu ve içeriğini alır.
    positions=[]
    for tag in ("div", "span", "p", "h1", "h2", "h3", "h4", "h5", "h6"):
        marker1='class="'+class_token
        marker2="class='"+class_token
        p1=fragment.find(marker1,start_pos)
        p2=fragment.find(marker2,start_pos)
        if p1<0: p=p2
        elif p2<0: p=p1
        else: p=min(p1,p2)
        if p>=0:
            ds=fragment.rfind("<"+tag,p)
            if ds>=0:
                positions.append((ds,tag))
    if not positions:
        return ""
    ds,tag=min(positions)
    block=_extract_div_from_pos(fragment,ds) if tag=="div" else ""
    if block:
        return block
    close="</"+tag+">"
    gt=fragment.find(">",ds)
    if gt<0: return ""
    e=fragment.find(close,gt+1)
    if e<0: return ""
    return fragment[ds:e+len(close)]


def _find_next_label(fragment, start_pos):
    best=-1
    for marker in ('class="card-label', "class='card-label"):
        p=fragment.find(marker,start_pos)
        if p>=0 and (best<0 or p<best):
            best=p
    return best


def _find_label_text(fragment, label_pos):
    gt=fragment.find(">",label_pos)
    if gt<0: return ""
    tag_start=fragment.rfind("<",0,label_pos)
    if tag_start<0: return ""
    tag_end=fragment.find(" ",tag_start+1)
    if tag_end<0: tag_end=fragment.find(">",tag_start+1)
    tag=fragment[tag_start+1:tag_end].strip()
    if not tag: return ""
    close="</"+tag+">"
    lt=fragment.find(close,gt+1)
    if lt<0: return strip_html_text(fragment[gt+1:])
    return strip_html_text(fragment[gt+1:lt])


def _extract_card_body(section):
    candidates=[]
    for marker in ('class="card-body', "class='card-body"):
        p=section.find(marker)
        if p>=0: candidates.append(p)
    if not candidates: return ""
    p=min(candidates)
    gt=section.find(">",p)
    if gt<0: return ""
    tag_start=section.rfind("<",0,p)
    if tag_start<0: return ""
    tag_end=section.find(" ",tag_start+1)
    if tag_end<0: tag_end=section.find(">",tag_start+1)
    tag=section[tag_start+1:tag_end].strip()
    if not tag: tag="div"
    if tag=="div":
        block=_extract_div_from_pos(section,tag_start)
        if block: return block
    close="</"+tag+">"
    e=section.find(close,gt+1)
    if e<0: return section[gt+1:]
    return section[gt+1:e]


def _parse_modal_evaluations(modal_html):
    """MicroPython-safe: yalnızca str.find ve temel string işlemleri kullanır."""
    if not modal_html:
        return []
    evaluations=[]
    seen=set()
    pos=0
    labels=[]
    while True:
        p=_find_next_label(modal_html,pos)
        if p<0: break
        labels.append(p); pos=p+1
    for i,p in enumerate(labels):
        label=_find_label_text(modal_html,p)
        if not label: continue
        low=label.lower()
        if "geri bildirim" in low or "hakem not" in low:
            continue
        section_start=modal_html.find(">",p)+1
        section_end=labels[i+1] if i+1<len(labels) else len(modal_html)
        section=modal_html[section_start:section_end]
        body_html=_extract_card_body(section)
        body=strip_html_text(body_html or section)
        score=_extract_numeric_token(body)
        if not score:
            value_pos=body_html.find("value=") if body_html else -1
            if value_pos>=0:
                q=body_html.find("\"",value_pos)
                q2=body_html.find("'",value_pos)
                if q<0 or (q2>=0 and q2<q): q=q2
                if q>=0:
                    qend=body_html.find(body_html[q],q+1)
                    if qend>q:
                        score=_extract_numeric_token(body_html[q+1:qend])
        if not score: continue
        key=label+"|"+score
        if key not in seen:
            seen.add(key)
            evaluations.append({"name":label,"score":score})
    return evaluations

def _parse_modal_feedback(modal_html):
    notes = []
    cards = _extract_all_divs_by_class(modal_html, "card border-top-0")
    seen = set()
    for card in cards:
        label = _extract_inner_text_after(card, 'class="card-label')
        if not label:
            label = _extract_inner_text_after(card, "class='card-label")
        label_lower = strip_html_text(label).lower()
        if "geri bildirim" not in label_lower:
            continue
        body = _extract_first_div_class(card, "card-body")
        if not body:
            continue
        # Hakem notlarındaki satır sonlarını koru.
        note = body.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
        note = strip_html_text(note)
        note = note.replace(" ;", ";")
        if note and note not in seen:
            seen.add(note)
            notes.append(note)
    return notes


def _stage_key_from_title(title):
    upper = strip_html_text(title).upper()

    # Video, rapor aşamalarından bağımsız gerçek bir değerlendirme aşamasıdır.
    # Örn: "KTR Başarılı/Video Durumu" ve "Video Hakem Değerlendirme Durumu".
    if "VIDEO" in upper:
        return "VIDEO"

    # "Proje Sunum Hakem Değerlendirme Durumu" ayrı bir değerlendirmedir.
    if "PROJE SUNUM" in upper and "HAKEM" in upper:
        return "PROJE_SUNUM"

    for token in (
        "DTR", "ÖTR", "OTR", "ÖDR", "ODR", "PDR",
        "KTR", "STR", "FTR", "PSR", "VTR", "MDR"
    ):
        if token in upper:
            if token == "OTR":
                return "ÖTR"
            if token == "ODR":
                return "ÖDR"
            return token

    return "GENEL"

def _stage_label(stage_key):
    labels = {
        "DTR": "DTR",
        "ÖTR": "ÖTR",
        "OTR": "ÖTR",
        "ÖDR": "ÖDR",
        "ODR": "ÖDR",
        "PDR": "PDR",
        "PROJE_SUNUM": "Proje Sunum",
        "PSR": "PSR",
        "FTR": "FTR",
        "STR": "STR",
        "VTR": "VTR",
        "MDR": "MDR",
        "KTR": "KTR",
        "VIDEO": "Video",
        "GENEL": "Genel",
    }
    return labels.get(stage_key, stage_key)



def _extract_modal_title(modal_html):
    """Modal başlığını alır; puanlı UI sekmesinin gerçek adını kullanmak için."""
    if not modal_html:
        return ""
    for marker in ('class="modal-title"', "class='modal-title'"):
        p = modal_html.find(marker)
        if p >= 0:
            gt = modal_html.find(">", p)
            if gt >= 0:
                lt = modal_html.find("<", gt + 1)
                if lt >= 0:
                    return strip_html_text(modal_html[gt + 1:lt])
    return ""


def _extract_modal_score(modal_html):
    """Puan modalındaki toplam puanı bulur. Kriter puanlarını toplam puanla karıştırmaz."""
    if not modal_html:
        return None
    text = strip_html_text(modal_html)
    # Önce açık toplam puan etiketlerini ara.
    for marker in ("Hakem Puanı", "Hakem Puani", "Puan :", "Puan:"):
        pos = text.find(marker)
        if pos >= 0:
            tail = text[pos:pos + 160]
            score_token = _extract_numeric_token(tail)
            if score_token:
                return score_token
    return None


def _generic_stage_key_from_title(title):
    """Bilinen token yoksa UI'daki gerçek modal başlığından stabil bir aşama anahtarı üretir."""
    title = strip_html_text(title)
    key = _stage_key_from_title(title)
    if key != "GENEL":
        return key
    compact = title.upper()
    for token in (" HAKEM DEĞERLENDİRME DURUMU", " HAKEM DEGERLENDIRME DURUMU", " DURUMU"):
        compact = compact.replace(token, "")
    compact = compact.replace("/", " ").replace("  ", " ").strip()
    if not compact:
        return "GENEL"
    # MicroPython-safe: yalnızca alfanümerik/alt çizgi mantığı.
    out = "CUSTOM_"
    for ch in compact:
        if (("0" <= ch <= "9") or
            ("a" <= ch <= "z") or
            ("A" <= ch <= "Z")):
            out += ch
        elif ch == "_":
            out += ch
        else:
            out += "_"
    while "__" in out:
        out = out.replace("__", "_")
    return out[:80]


def _stage_label_from_title(title):
    key = _stage_key_from_title(title)
    if key != "GENEL":
        return _stage_label(key)
    clean = strip_html_text(title)
    for suffix in (
        " Hakem Değerlendirme Durumu",
        " Hakem Degerlendirme Durumu",
        " Durumu",
    ):
        if clean.endswith(suffix):
            clean = clean[:-len(suffix)].strip()
    # Yarışma adı başlığı içeriyorsa son anlamlı parça kalsın.
    if "/" in clean:
        clean = clean.split("/")[-1].strip()
    if not clean:
        clean = "Genel"
    return clean


def parse_competition_detail_html(html, fallback_program=""):
    """T3 KYS detay sayfasını UI'daki gerçek puanlı değerlendirme modallarına göre gruplar.

    Her puanlı UI sekmesi tek bir stage kaydıdır:
      score + score_date + evaluations + notes + events

    Aşama adı DTR/ÖTR/... ile sınırlı değildir. Modal başlığı ne diyorsa o
    değerlendirme UI aşaması olarak korunur. Böylece ÖDR, Proje Sunum, Video
    ve ileride eklenecek başka değerlendirme türleri de otomatik yakalanır.
    """
    result = {
        "schema_version": 6,
        "program": clean_html(fallback_program),
        "title": "",
        "record_id": "",
        "source_url": "",
        "current_stage": "",
        "score": None,
        "score_date": "",
        "score_evaluation": "",
        "events": [],
        "stages": [],
        "evaluations": [],
        "notes": [],
    }

    raw = str(html or "")
    if not raw:
        return result

    try:
        title_pos = raw.find('class="text-dark-75 fw-bold')
        if title_pos >= 0:
            gt = raw.find(">", title_pos)
            lt = raw.find("<", gt + 1) if gt >= 0 else -1
            if gt >= 0 and lt >= 0:
                result["title"] = strip_html_text(raw[gt + 1:lt])
        if result["program"]:
            result["title"] = result["program"]

        timeline_positions = _find_all_positions(raw, 'class="timeline-item')
        if not timeline_positions:
            timeline_positions = _find_all_positions(raw, "class='timeline-item")

        events = []
        scored = []
        seen_events = set()

        for idx in range(len(timeline_positions)):
            pos = timeline_positions[idx]
            end = timeline_positions[idx + 1] if idx + 1 < len(timeline_positions) else min(len(raw), pos + 50000)
            block = raw[pos:end]

            event_title = _extract_inner_text_after(block, 'class="text-dark-75 fw-bold')
            if not event_title:
                event_title = _extract_inner_text_after(block, "class='text-dark-75 fw-bold")

            event_date = _extract_inner_text_after(block, 'style="color:#9d9999">')
            if not event_date:
                event_date = _extract_inner_text_after(block, "style='color:#9d9999'>")

            event_score = None
            search = 0
            while True:
                p = block.find("Puan :", search)
                if p < 0:
                    p = block.find("Puan:", search)
                if p < 0:
                    break
                tail = block[p:p + 600]
                score_token = _extract_numeric_token(tail)
                if score_token:
                    event_score = score_token
                search = p + 5

            event = {"date": event_date, "score": event_score, "title": event_title}
            event_key = (event_title, event_date, event_score)
            if event_key not in seen_events and (event_title or event_date or event_score is not None):
                seen_events.add(event_key)
                events.append(event)

            # T3 KYS'de bazı sayfalarda Hakem Formu bağlantısı doğrudan
            # kt_tab_pane_3_<id> modalını açar. Bu modal tek başına hem
            # değerlendirme kriterlerini hem de Geri Bildirim accordion
            # bölümünü içerir. Daha önce 3=feedback / 2=score varsayımı
            # yapılmıştı; bu FPV Drone gibi sayfalarda yanlıştı.
            #
            # Bu nedenle bağlantı hedefindeki 2 veya 3 modalından hangisi
            # gerçekten değerlendirme içeriği taşıyorsa onu kullanıyoruz.
            target_ids = _find_attr_target_ids(block)
            detail_modal_ids = []

            # Önce 3 numaralı modalı tercih et; kaynak HTML'lerde Hakem Formu
            # çoğunlukla buraya bağlanıyor.
            for target_id in target_ids:
                if "kt_tab_pane_3_" in target_id:
                    if target_id not in detail_modal_ids:
                        detail_modal_ids.append(target_id)

            # Bazı yarışmalarda 2 numaralı modal kullanılabilir.
            for target_id in target_ids:
                if "kt_tab_pane_2_" in target_id:
                    if target_id not in detail_modal_ids:
                        detail_modal_ids.append(target_id)

            for target_id in detail_modal_ids:
                modal = _extract_div_by_id(raw, target_id)
                if not modal:
                    continue

                modal_title = _extract_modal_title(modal)
                modal_score = _extract_modal_score(modal)
                if modal_score is None and event_score is not None:
                    modal_score = event_score

                # Bu modalın kendisi puanlı değerlendirme modalıysa stage oluştur.
                if modal_score is None:
                    # Yine de kriter/not içeriği varsa timeline puanını kullanabiliriz.
                    modal_evaluations = _parse_modal_evaluations(modal)
                    modal_notes = _parse_modal_feedback(modal)
                    if not modal_evaluations and not modal_notes:
                        continue
                else:
                    modal_evaluations = _parse_modal_evaluations(modal)
                    modal_notes = _parse_modal_feedback(modal)

                stage_source_title = modal_title or event_title
                stage_key = _generic_stage_key_from_title(stage_source_title)
                stage_label = _stage_label_from_title(stage_source_title)

                stage = {
                    "key": stage_key,
                    "label": stage_label,
                    "title": stage_source_title,
                    "score": modal_score,
                    "score_date": event_date,
                    "evaluations": modal_evaluations,
                    "notes": modal_notes,
                    "events": [event],
                    "score_modal_id": target_id,
                    "feedback_modal_id": target_id,
                }
                scored.append(stage)

        # Timeline'daki PUANLI hareketleri daima ayrı bir stage adayı olarak kullan.
        # UI modalı bulunmuş olsa bile, bazı yarışmalarda modal başlığı/link yapısı
        # farklı olduğundan onu atlamayız. Böylece aynı sayfada örneğin ÖDR +
        # Proje Sunum puanları iki ayrı stage olarak korunur.
        score_events = []
        for event in events:
            if event.get("score") is None:
                continue
            score_events.append(event)

        for event in score_events:
            event_title = event.get("title", "") or ""
            stage_key = _generic_stage_key_from_title(event_title)

            already_has_key = False
            for existing in scored:
                if existing.get("key") == stage_key:
                    # Aynı stage için modal kaydı varsa onun zengin verisini koruyoruz.
                    # Timeline bilgisi eksikse sonradan ekleyeceğiz.
                    existing_events = existing.get("events")
                    if not isinstance(existing_events, list):
                        existing_events = []
                        existing["events"] = existing_events
                    duplicate = False
                    for ee in existing_events:
                        if (ee.get("title"), ee.get("date"), ee.get("score")) == (
                            event.get("title"), event.get("date"), event.get("score")
                        ):
                            duplicate = True
                            break
                    if not duplicate:
                        existing_events.append(event)
                    already_has_key = True
                    break

            if already_has_key:
                continue

            scored.append({
                "key": stage_key,
                "label": _stage_label_from_title(event_title),
                "title": event_title,
                "score": event.get("score"),
                "score_date": event.get("date", ""),
                "evaluations": [],
                "notes": [],
                "events": [event],
                "score_modal_id": "",
                "feedback_modal_id": "",
            })

        # Aynı stage birden fazla modalda bulunabilir (örn. 2=puan, 3=geri bildirim).
        # Aynı key için değerlendirme kriteri/not içeriği daha zengin olan kaydı koru.
        stages = []
        by_key = {}
        for item in scored:
            key = item.get("key") or "GENEL"
            existing = by_key.get(key)
            if existing is None:
                by_key[key] = item
                stages.append(item)
                continue

            existing_e = existing.get("evaluations") or []
            item_e = item.get("evaluations") or []
            existing_n = existing.get("notes") or []
            item_n = item.get("notes") or []

            # Zengin modalı tercih et; eksik alandaki bilgileri de tamamla.
            if len(item_e) > len(existing_e):
                existing["evaluations"] = item_e
            if len(item_n) > len(existing_n):
                existing["notes"] = item_n
            if not existing.get("score") and item.get("score"):
                existing["score"] = item.get("score")
            if not existing.get("score_date") and item.get("score_date"):
                existing["score_date"] = item.get("score_date")
            if not existing.get("score_modal_id") and item.get("score_modal_id"):
                existing["score_modal_id"] = item.get("score_modal_id")
            if not existing.get("feedback_modal_id") and item.get("feedback_modal_id"):
                existing["feedback_modal_id"] = item.get("feedback_modal_id")

        result["events"] = events
        result["stages"] = stages

        if stages:
            current = stages[0]
            result["current_stage"] = current.get("key", "")
            result["score"] = current.get("score")
            result["score_date"] = current.get("score_date", "")
            result["score_evaluation"] = current.get("title", "")
            result["evaluations"] = current.get("evaluations", [])
            result["notes"] = current.get("notes", [])

        if result["score"] is None:
            search = 0
            last_score = None
            while True:
                p = raw.find("Puan :", search)
                if p < 0:
                    p = raw.find("Puan:", search)
                if p < 0:
                    break
                tail = raw[p:p + 600]
                score_token = _extract_numeric_token(tail)
                if score_token:
                    last_score = score_token
                search = p + 5
            result["score"] = last_score

    except Exception as exc:
        log("Detay HTML parse hatasi: {}".format(exc))

    return result

def load_competition_details():
    data = load_json(COMPETITION_DETAILS_FILE, {})
    if isinstance(data, dict):
        return data
    return {}

def save_competition_details(data):
    save_json(COMPETITION_DETAILS_FILE, data)

def _detail_record_id(competition):
    ids = competition.get("ids", []) if isinstance(competition, dict) else []
    for item in ids:
        value = str(item or "").strip()
        if value:
            return value
    return ""

def fetch_competition_detail(record_id, fallback_program=""):
    global http_session

    record_id = str(record_id or "").strip()
    if not record_id:
        raise RuntimeError("Detay için başvuru ID bulunamadı.")
    if http_session is None or not http_session.logged_in:
        raise RuntimeError("Detay için aktif HTTP oturumu gerekli.")

    url = BASE_URL + "/tr/mainpage/applications/evaluations/{}/".format(record_id)
    response = None
    try:
        response = urequests.get(
            url,
            headers=http_session.headers({
                "Referer": T3_URL,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }),
            timeout=HTTP_TIMEOUT,
        )
        if waf_detected(response):
            raise RuntimeError("Değerlendirme detayında WAF challenge.")
        if response.status_code in (401, 403):
            raise PermissionError("Detay oturumu reddetti: HTTP {}".format(response.status_code))
        if response.status_code != 200:
            raise RuntimeError("Detay HTTP {}".format(response.status_code))
        html = response.text
        detail = parse_competition_detail_html(html, fallback_program)
        detail["schema_version"] = 6
        detail["record_id"] = record_id
        detail["source_url"] = url
        detail["fetched_at"] = time.time()
        return detail
    finally:
        if response is not None:
            try:
                response.close()
            except Exception:
                pass
        gc.collect()

def sync_competition_details(competitions, affected_programs=None, force_all=False):
    details = load_competition_details()
    if not isinstance(affected_programs, set):
        affected_programs = set(affected_programs or [])

    changed = False
    for competition in competitions:
        program = clean_html(competition.get("program"))
        if not program:
            continue
        record_id = _detail_record_id(competition)
        if not record_id:
            continue

        cached = details.get(program)
        must_fetch = (
            force_all
            or not isinstance(cached, dict)
            or int(cached.get("schema_version", 0) or 0) < 6
            or str(cached.get("record_id", "")) != record_id
            or not isinstance(cached.get("stages"), list)
            or program in affected_programs
        )
        if not must_fetch:
            continue

        try:
            details[program] = fetch_competition_detail(record_id, program)
            changed = True
            log("Yarışma detayı yenilendi: {}".format(program))
        except Exception as exc:
            log("Yarışma detayı alınamadı: {} / {}".format(program, exc))

    if changed:
        save_competition_details(details)
    del details
    gc.collect()
    return True

def refresh_one_competition_detail(record_id):
    competitions = load_json(COMPETITIONS_FILE, [])
    if not isinstance(competitions, list):
        raise RuntimeError("Yarışma önbelleği okunamadı.")

    for competition in competitions:
        ids = competition.get("ids", []) if isinstance(competition, dict) else []
        if str(record_id) in [str(x) for x in ids]:
            program = clean_html(competition.get("program"))
            detail = fetch_competition_detail(record_id, program)
            details = load_competition_details()
            details[program] = detail
            save_competition_details(details)
            return detail

    raise RuntimeError("Yarışma bulunamadı: {}".format(record_id))

def parse_record_timestamp(value):
    if value is None:
        return -1

    try:
        if isinstance(value, (int, float)):
            return float(value)
    except Exception:
        pass

    raw = str(value).strip()

    if not raw:
        return -1

    # ISO benzeri zamanları mümkün olduğunca sıralanabilir timestamp'e çevir.
    # MicroPython'da tam datetime parser her sürümde bulunmadığı için
    # basit bir alan parser kullanıyoruz.
    try:
        normalized = raw.replace("T", " ")
        normalized = normalized.replace("Z", "")
        if "." in normalized:
            normalized = normalized.split(".", 1)[0]

        date_part = normalized.split(" ", 1)[0]
        time_part = "00:00:00"

        if " " in normalized:
            time_part = normalized.split(" ", 1)[1][:8]

        d = date_part.split("-")
        t = time_part.split(":")

        if len(d) >= 3 and len(t) >= 2:
            year = int(d[0])
            month = int(d[1])
            day = int(d[2])
            hour = int(t[0])
            minute = int(t[1])
            second = int(t[2]) if len(t) > 2 else 0

            # Epoch dönüşümü için time.mktime mevcutsa kullan.
            try:
                return time.mktime(
                    (year, month, day, hour, minute, second, 0, 0)
                )
            except Exception:
                # Tarih sıralaması için YYYYMMDDHHMMSS sayısal anahtar.
                return float(
                    "{}{:02d}{:02d}{:02d}{:02d}{:02d}".format(
                        year, month, day,
                        hour, minute, second
                    )
                )
    except Exception:
        pass

    return -1

def sort_records_by_application_date(records):
    return sorted(
        records,
        key=lambda r: parse_record_timestamp(
            r.get("created_at")
        ),
        reverse=True
    )

def make_application_view_from_state(state, record):
    program = state.get("program", "")
    status = state.get("status", "")
    movements = state.get("movements", "")

    status_key, competition_year, status_icon, status_label = (
        classify_competition(
            program,
            status,
            movements
        )
    )

    return {
        "id": state.get("id", ""),
        "program": program,
        "created_at": clean_html(
            record.get("created_at")
        ),
        "status": status,
        "status_key": status_key,
        "status_icon": status_icon,
        "status_label": status_label,
        "competition_year": competition_year,
        "is_eliminated": state.get("is_eliminated"),
        "applicant_or_team": clean_html(
            record.get("applicant_or_team")
        ),
        "movements": movements,
        "certificate_url": state.get(
            "certificate_url",
            ""
        ),
    }

def make_application_view(record):
    state = make_state(record)
    view = make_application_view_from_state(
        state,
        record
    )
    del state
    return view

def announcement_hour_histogram():
    histogram = [0] * 24
    changes = load_changes()

    for item in changes[-MAX_CHANGES:]:
        try:
            ts = float(item.get("timestamp", 0))
            if ts <= 0:
                continue

            # T3 KYS saatlerini Türkiye yerel saatine yaklaştır.
            lt = time.localtime(int(ts + TRT_OFFSET_SECONDS))
            hour = int(lt[3])

            if 0 <= hour < 24:
                histogram[hour] += 1
        except Exception:
            pass

    return histogram

def calculate_next_delay():
    hist = announcement_hour_histogram()
    total = sum(hist)

    min_delay = max(30, int(MIN_CHECK_INTERVAL))
    max_delay = max(min_delay, int(MAX_CHECK_INTERVAL))
    nominal = max(
        min_delay,
        min(max_delay, int(CHECK_INTERVAL))
    )

    base = nominal + random.randint(
        -JITTER_SECONDS,
        JITTER_SECONDS
    )

    if total <= 0:
        return max(
            MIN_CHECK_INTERVAL,
            min(MAX_CHECK_INTERVAL, base)
        )

    # En çok değişiklik görülen saatler daha sık kontrol edilir.
    now = int(time.time() + TRT_OFFSET_SECONDS)
    try:
        current_hour = time.localtime(now)[3]
    except Exception:
        current_hour = 12

    score = 0
    for offset in (-2, -1, 0, 1, 2):
        hour = (current_hour + offset) % 24
        score += hist[hour] * (3 if offset == 0 else 1)

    peak = max(hist) if hist else 0
    if peak <= 0:
        probability = 0.0
    else:
        probability = min(1.0, score / float(max(1, peak * 3)))

    # Yüksek geçmiş yoğunluk -> daha kısa bekleme,
    # düşük yoğunluk -> daha uzun bekleme.
    delay = max_delay - int(
        (max_delay - min_delay) * probability
    )

    delay += random.randint(
        -JITTER_SECONDS,
        JITTER_SECONDS
    )

    return max(
        min_delay,
        min(max_delay, delay)
    )

def schedule_next_check():
    delay = calculate_next_delay()
    monitor_state["next_check"] = time.time() + delay
    monitor_state["next_check_delay"] = delay
    save_monitor_state()
    return delay

def perform_check():
    global _unread_changes

    led_set_error(False)
    led_set_check(True)

    records_count = 0
    current = {}
    applications = []
    competition_map = {}
    previous = None
    new_changes = []
    change_log = []
    changed_programs = set()

    try:
        # Önceki durum karşılaştırma için bir kez yüklenir.
        previous = load_json(STATE_FILE, {})
        first_scan = not bool(previous)

        for record in iter_application_rows():
            record_id = str(record.get("id", ""))

            if not record_id:
                continue

            records_count += 1

            # Aynı temizlenmiş string'ler state / applications / competitions
            # tarafında mümkün olduğunca paylaşılır.
            state = make_state(record)
            current[record_id] = state

            applications.append(
                make_application_view_from_state(
                    state,
                    record
                )
            )

            program = state.get("program", "")

            if program:
                item = competition_map.get(program)

                if item is None:
                    item = {
                        "program": program,
                        "ids": [],
                        "statuses": [],
                        "count": 0,
                        "last_change": None,
                        "status_key": "evaluation",
                        "status_icon": "⌛",
                        "status_label": "Değerlendirme",
                        "competition_year": None,
                    }
                    competition_map[program] = item

                if record_id and record_id not in item["ids"]:
                    item["ids"].append(record_id)

                status = state.get("status", "")
                movements = state.get("movements", "")
                status_key, competition_year, status_icon, status_label = (
                    classify_competition(
                        program,
                        status,
                        movements
                    )
                )

                if status and status not in item["statuses"]:
                    item["statuses"].append(status)

                priority = {
                    "appeal": 6,
                    "winner": 5,
                    "success": 4,
                    "fail": 3,
                    "applied": 2,
                    "evaluation": 1,
                }

                current_key = item.get(
                    "status_key",
                    "evaluation"
                )

                if priority.get(
                    status_key,
                    1
                ) >= priority.get(
                    current_key,
                    1
                ):
                    item["status_key"] = status_key
                    item["status_icon"] = status_icon
                    item["status_label"] = status_label

                item["competition_year"] = competition_year
                item["count"] += 1

            old = previous.get(record_id)

            if old is None:
                changed_programs.add(program)
                continue

            field_changes = compare_states(old, state)

            if field_changes:
                changed_programs.add(program)
                item = add_change(
                    state,
                    field_changes
                )

                new_changes.append(item)
                change_log.append(
                    (
                        item["program"],
                        item["record_id"]
                    )
                )

# +++ YENİ EKLENEN KISIM: Veri Değişikliği Kontrolü +++
        has_data_changed = (
            first_scan or 
            (len(new_changes) > 0) or 
            (len(changed_programs) > 0) or 
            (records_count != len(previous))
        )

        # previous artık tamamen gereksiz; büyük eski state sözlüğünü serbest bırak.
        del previous
        previous = None
        gc.collect()

        # --------------------------------------------------------
        # STATE
        # --------------------------------------------------------
        if has_data_changed:
            save_json(STATE_FILE, current)

        del current
        current = None
        gc.collect()

        # --------------------------------------------------------
        # BAŞVURULAR
        # --------------------------------------------------------
        applications.sort(
            key=lambda r: parse_record_timestamp(
                r.get("created_at")
            ),
            reverse=True
        )

        if has_data_changed:
            save_json(APPLICATIONS_FILE, applications)

        del applications
        applications = None
        gc.collect()

        # --------------------------------------------------------
        # YARIŞMALAR
        # --------------------------------------------------------
        competitions = list(competition_map.values())

        competitions.sort(
            key=lambda x: x["program"].lower()
        )

        total_programs = len(competitions)
        monitor_state["stats"] = build_statistics(
            competitions
        )

        if has_data_changed:
            save_json(COMPETITIONS_FILE, competitions)

        # Detaylar eksikse (örn. önceki denemede ağ hatası olduysa) tamamlasın diye her zaman çağırılır.
        # Bu fonksiyon kendi içinde zaten sadece değişen/eksik detayları Flash'a yazar.
        sync_competition_details(
            competitions,
            affected_programs=changed_programs,
            force_all=first_scan,
        )

        del competitions
        competitions = None

        del competition_map
        competition_map = None
        gc.collect()

        # --------------------------------------------------------
        # DEĞİŞİKLİK GEÇMİŞİ
        # --------------------------------------------------------
        if new_changes:
            history = load_changes()
            history.extend(new_changes)

            save_changes(history)

            del history
            gc.collect()

            _unread_changes += len(new_changes)

        changes_count = len(new_changes)

        if new_changes and not first_scan:
            log("ALARM: {} yeni okunmamış değişiklik; LED alarmi aktif.".format(len(new_changes)))
            led_start_alert()

            log(
                "{} değişiklik bulundu.".format(
                    changes_count
                )
            )

            for program, record_id in change_log:
                log(
                    "DEĞİŞİKLİK: {} / ID={}".format(
                        program,
                        record_id
                    )
                )

        # finally bloğunda tekrar kontrol edileceği için değişkeni silmek yerine
        # None yapıyoruz. Önceki sürümde burada del kullanılması, return sırasında
        # finally çalışınca "local variable referenced before assignment" üretiyordu.
        new_changes = None
        change_log = None
        gc.collect()

        now = time.time()

        monitor_state["last_check"] = now
        monitor_state["total_applications"] = records_count
        monitor_state["total_programs"] = total_programs
        monitor_state["first_scan_completed"] = True
        monitor_state["last_error"] = None
        monitor_state["running"] = True
        monitor_state["waiting_login"] = False
        save_monitor_state()
        led_set_check(False)

        return {
            "records": records_count,
            "programs": total_programs,
            "changes": changes_count,
        }

    finally:
        if previous is not None:
            del previous

        if current is not None:
            del current

        if applications is not None:
            del applications

        if competition_map is not None:
            del competition_map

        if new_changes is not None:
            del new_changes

        if change_log is not None:
            del change_log

        if changed_programs is not None:
            del changed_programs

        gc.collect()

# ============================================================
# WEB DASHBOARD
#
# Dashboard HTML ayrı dosyada tutuluyor. Böylece ~64 KB HTML
# main.py yüklenirken MicroPython heap'ine sabit string olarak alınmıyor.
# HTML, HTTP isteği geldiğinde Flash'tan 1024 byte parçalar halinde stream edilir.
# ============================================================

HTML_FILE = "index.html"



# ============================================================
# DASHBOARD API
# ============================================================

def _send_bytes(client, data):
    try:
        sendall = client.sendall
    except AttributeError:
        sendall = None

    if sendall is not None:
        sendall(data)
    else:
        client.send(data)

def json_response(client, status, data):
    # dumps() -> encode() yalnızca bir kez yapılır.
    # Eski kod aynı JSON'u Content-Length hesabında bir kez,
    # gerçek gönderimde bir kez daha encode ediyordu.
    body = ujson.dumps(data)
    body_bytes = body.encode("utf-8")
    del body

    header = (
        "HTTP/1.1 {}\r\n"
        "Content-Type: application/json; charset=utf-8\r\n"
        "Content-Length: {}\r\n"
        "Cache-Control: no-store\r\n"
        "Connection: close\r\n"
        "\r\n"
    ).format(
        status,
        len(body_bytes)
    )

    _send_bytes(
        client,
        header.encode("utf-8")
    )
    _send_bytes(client, body_bytes)

    del header
    del body_bytes
    gc.collect()

def file_json_response(client, status, filename):
    # Flash'taki JSON'u tekrar load -> dumps -> encode yapmadan,
    # küçük parçalar halinde doğrudan HTTP'ye aktar.
    header = (
        "HTTP/1.1 {}\r\n"
        "Content-Type: application/json; charset=utf-8\r\n"
        "Cache-Control: no-store\r\n"
        "Connection: close\r\n"
        "\r\n"
    ).format(status)

    _send_bytes(
        client,
        header.encode("utf-8")
    )
    del header

    try:
        with open(filename, "rb") as f:
            while True:
                chunk = f.read(1024)

                if not chunk:
                    break

                _send_bytes(client, chunk)
                del chunk

    except Exception:
        # Dosya yoksa minimal bir JSON gövdesi döndür.
        _send_bytes(client, b"[]")

    gc.collect()

def html_response(client, status):
    # HTML'yi RAM'e komple almak yerine Flash'tan küçük parçalar halinde gönder.
    try:
        import os
        content_length = os.stat(HTML_FILE)[6]
    except Exception:
        content_length = None

    header = (
        "HTTP/1.1 {}\r\n"
        "Content-Type: text/html; charset=utf-8\r\n"
        "{}"
        "Cache-Control: no-store, no-cache, must-revalidate, max-age=0\r\n"
        "Pragma: no-cache\r\n"
        "X-T3-Dashboard-Version: 2026.09.07-split\r\n"
        "Connection: close\r\n"
        "\r\n"
    ).format(
        status,
        ("Content-Length: {}\r\n".format(content_length))
        if content_length is not None else ""
    )

    try:
        _send_bytes(client, header.encode("utf-8"))
        del header

        with open(HTML_FILE, "rb") as f:
            while True:
                chunk = f.read(1024)
                if not chunk:
                    break
                _send_bytes(client, chunk)
                del chunk
    except OSError as exc:
        log("HTML dosyası okunamadı: {}".format(exc))
        # Header gönderildiyse burada ikinci bir HTTP cevabı göndermeye çalışma.
    finally:
        gc.collect()


# ============================================================
# SERTİFİKALAR
# ============================================================

def load_hidden_certificates():
    data = load_json(CERTIFICATES_FILE, {})
    if isinstance(data, dict):
        ids = data.get("hidden_ids", [])
    elif isinstance(data, list):
        ids = data
    else:
        ids = []
    if not isinstance(ids, list):
        ids = []
    return [str(x) for x in ids if str(x)]


def save_hidden_certificates(hidden_ids):
    clean = []
    seen = set()
    for value in hidden_ids if isinstance(hidden_ids, list) else []:
        key = str(value)
        if key and key not in seen:
            seen.add(key)
            clean.append(key)
    save_json(CERTIFICATES_FILE, {"hidden_ids": clean})


def certificate_identity(item):
    if not isinstance(item, dict):
        return ""
    value = item.get("id")
    if value is not None and str(value):
        return str(value)
    # ID beklenmedik şekilde boşsa kaydı yine de tekilleştir.
    return "|".join((
        str(item.get("program", "")),
        str(item.get("created_at", "")),
    ))


def is_certificate_record(item):
    if not isinstance(item, dict):
        return False
    url = extract_url(item.get("certificate_url"))
    return bool(url)


def certificate_records():
    applications = load_json(APPLICATIONS_FILE, [])
    if not isinstance(applications, list):
        applications = []

    hidden = set(load_hidden_certificates())
    visible_rows = []
    hidden_rows = []

    for item in applications:
        if not is_certificate_record(item):
            continue

        certificate_id = str(item.get("id", "")).strip()
        row = {
            "id": certificate_id,
            "program": clean_html(item.get("program")),
            "status": clean_html(item.get("status")),
            "status_key": str(item.get("status_key", "evaluation")),
            "status_label": clean_html(
                item.get("status_label") or item.get("status")
            ),
            "status_icon": clean_html(item.get("status_icon") or "📜"),
            "competition_year": item.get("competition_year"),
            "created_at": clean_html(item.get("created_at")),
            "applicant_or_team": clean_html(item.get("applicant_or_team")),
            "certificate_id": certificate_id,
        }
        key = certificate_identity(row)
        row["hidden_id"] = key

        if key in hidden:
            hidden_rows.append(row)
        else:
            visible_rows.append(row)

    visible_rows.sort(
        key=lambda x: parse_float_date_for_sort(x.get("created_at")),
        reverse=True
    )
    hidden_rows.sort(
        key=lambda x: parse_float_date_for_sort(x.get("created_at")),
        reverse=True
    )

    return {
        "visible": visible_rows,
        "hidden": hidden_rows,
        "total": len(visible_rows) + len(hidden_rows),
        "hidden_total": len(hidden_rows),
    }


def parse_float_date_for_sort(value):
    if value is None:
        return 0.0
    try:
        text=str(value).strip()
        if not text:
            return 0.0
        try:
            return float(text)
        except Exception:
            pass
        digits=[]
        for ch in text:
            if "0" <= ch <= "9":
                digits.append(ch)
        if not digits:
            return 0.0
        joined="".join(digits[:16])
        return float(joined or 0)
    except Exception:
        return 0.0

def api_certificates():
    result = certificate_records()
    gc.collect()
    return result


def hide_certificate(certificate_id):
    key = str(certificate_id or "").strip()
    if not key:
        return {"ok": False, "error": "Sertifika kimliği boş."}

    hidden = load_hidden_certificates()
    if key not in hidden:
        hidden.append(key)
        save_hidden_certificates(hidden)

    gc.collect()
    return {"ok": True, "hidden_id": key}


def restore_certificate(certificate_id):
    key = str(certificate_id or "").strip()
    if not key:
        return {"ok": False, "error": "Sertifika kimliği boş."}

    hidden = load_hidden_certificates()
    hidden = [item for item in hidden if str(item) != key]
    save_hidden_certificates(hidden)

    gc.collect()
    return {"ok": True, "hidden_id": key}


def _safe_certificate_filename(record, ext=".pdf"):
    if not isinstance(record, dict):
        return "T3_KYS_Sertifika" + ext

    parts = []
    
    # 1. Ad Soyad / Takım Adı
    applicant = clean_html(record.get("applicant_or_team", ""))
    if applicant:
        parts.append(applicant)
        
    # 2. Yarışma Adı
    program = clean_html(record.get("program", ""))
    if program:
        parts.append(program)
        
    # 3. Yıl
    year = str(record.get("competition_year") or "")
    if year and year != "None":
        parts.append(year)
        
    # 4. Sertifika ID
    cert_id = str(record.get("id") or "")
    if cert_id:
        parts.append(cert_id)
        
    # 5. Durum
    status = clean_html(record.get("status_label") or record.get("status", ""))
    if status:
        parts.append(status)

    raw_name = "_".join(parts) if parts else "T3_KYS_Sertifika"

    # Türkçe karakterleri ve boşlukları güvenli karakterlere dönüştür
    replacements = (
        ("İ", "I"), ("ı", "i"), ("Ş", "S"), ("ş", "s"),
        ("Ç", "C"), ("ç", "c"), ("Ö", "O"), ("ö", "o"),
        ("Ü", "U"), ("ü", "u"), ("Ğ", "G"), ("ğ", "g"),
        (" ", "_"), ("/", "_"), ("\\", "_")
    )
    for old_char, new_char in replacements:
        raw_name = raw_name.replace(old_char, new_char)

    out = []
    for ch in raw_name:
        if (("a" <= ch <= "z") or ("A" <= ch <= "Z") or
                ("0" <= ch <= "9") or ch in "-_."):
            out.append(ch)

    name = "".join(out).strip("_.")
    # Dosya adının sistem sınırlarını (Windows) aşmaması için kırpıyoruz
    return name[:120] + ext
    program = clean_html(record.get("program")) if isinstance(record, dict) else ""
    value = program or "T3_KYS_Sertifika"
    out = []
    for ch in str(value):
        if (("a" <= ch <= "z") or ("A" <= ch <= "Z") or
                ("0" <= ch <= "9") or ch in "-_."):
            out.append(ch)
        elif ch in " _-":
            out.append("_")
    name = "".join(out).strip("_.") or "T3_KYS_Sertifika"
    return name[:80] + ".pdf"


def _certificate_by_id(certificate_id):
    wanted = str(certificate_id or "").strip()
    if not wanted:
        return None
    applications = load_json(APPLICATIONS_FILE, [])
    if not isinstance(applications, list):
        return None
    for item in applications:
        if not isinstance(item, dict):
            continue
        if str(item.get("id", "")).strip() != wanted:
            continue
        if not str(item.get("certificate_url", "") or "").strip():
            return None
        return item
    return None


def _certificate_request(url):
    """Sertifika URL'sini aktif T3 oturumu ile alır; sayfa/link ise PDF href'ini bulur."""
    global http_session
    current_url = str(url or "").strip()
    for attempt in range(2):
        response = None
        try:
            response = urequests.get(
                current_url,
                headers=http_session.headers({
                    "Referer": T3_URL,
                    "Accept": "application/pdf,application/octet-stream,text/html;q=0.9,*/*;q=0.8",
                }),
                timeout=HTTP_TIMEOUT,
            )
            status = getattr(response, "status_code", 0)

            if status in (401, 403):
                if attempt == 0:
                    try:
                        response.close()
                    except Exception:
                        pass
                    response = None
                    log("Sertifika oturumu reddedildi; T3 oturumu yenileniyor...")
                    t3_login()
                    continue
                raise PermissionError("Sertifika oturumu reddedildi: HTTP {}".format(status))

            if status < 200 or status >= 300:
                raise RuntimeError("Sertifika HTTP {}".format(status))

            content_type = "application/octet-stream"
            try:
                content_type = response.headers.get("Content-Type", content_type)
                content_type = content_type.split(";", 1)[0].strip().lower()
            except Exception:
                pass

            if content_type.startswith("text/html"):
                html = response.text
                next_url = extract_url(html)
                try:
                    response.close()
                except Exception:
                    pass
                response = None
                if next_url and next_url != current_url and next_url.startswith(("http://", "https://")):
                    current_url = next_url
                    continue
                if attempt == 0:
                    log("Sertifika URL'si giriş sayfası döndürdü; T3 oturumu yenileniyor...")
                    t3_login()
                    continue
                raise PermissionError("Sertifika dosyası yerine giriş sayfası döndü.")

            return response, content_type, current_url
        except Exception:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass
            raise

    raise RuntimeError("Sertifika alınamadı.")


def certificate_download_response(client, certificate_id):
    global http_session

    # Sertifika PDF'si T3 KYS'den alınırken birkaç saniyeden uzun sürebilir.
    # Dashboard istemci socket'inin genel kısa timeout'u burada kullanılmamalı.
    try:
        client.settimeout(max(60, HTTP_TIMEOUT + 30))
    except Exception:
        pass
    if http_session is None or not http_session.logged_in:
        json_response(client, "401 Unauthorized", {"ok": False, "error": "T3 KYS oturumu aktif değil."})
        return

    record = _certificate_by_id(certificate_id)
    if record is None:
        json_response(client, "404 Not Found", {"ok": False, "error": "Sertifika bulunamadı."})
        return

    url = extract_url(record.get("certificate_url"))
    if not url:
        json_response(client, "404 Not Found", {"ok": False, "error": "Sertifika bağlantısı bulunamadı."})
        return

    response = None
    try:
        gc.collect()
        response, content_type, final_url = _certificate_request(url)

        content_length = None
        try:
            raw_length = response.headers.get("Content-Length")
            if raw_length is not None:
                content_length = int(raw_length)
        except Exception:
            content_length = None
        # Gelen dosya formatını algıla ve doğru uzantıyı belirle
        ctype = str(content_type).lower()
        if "jpeg" in ctype or "jpg" in ctype:
            ext = ".jpg"
            out_ctype = "image/jpeg"
        elif "png" in ctype:
            ext = ".png"
            out_ctype = "image/png"
        else:
            ext = ".pdf"
            out_ctype = "application/pdf"

        # Dosya adını akıllı şablon ve doğru uzantı ile oluştur
        filename = _safe_certificate_filename(record, ext)
        
        header = (
            "HTTP/1.1 200 OK\r\n"
            "Content-Type: {}\r\n"
            "Content-Disposition: attachment; filename=\"{}\"\r\n"
            "Cache-Control: no-store, no-cache, must-revalidate, max-age=0\r\n"
            "Pragma: no-cache\r\n"
            "X-Content-Type-Options: nosniff\r\n"
        ).format(out_ctype, filename)
        if content_length is not None and content_length >= 0:
            header += "Content-Length: {}\r\n".format(content_length)
        header += "Connection: close\r\n\r\n"
        _send_bytes(client, header.encode("utf-8"))
        del header

        raw_stream = getattr(response, "raw", None)
        if raw_stream is not None and hasattr(raw_stream, "read"):
            while True:
                chunk = raw_stream.read(2048)
                if not chunk:
                    break
                _send_bytes(client, chunk)
                del chunk
        else:
            data = response.content
            try:
                _send_bytes(client, data)
            finally:
                del data

        log("Sertifika gönderildi: {}".format(final_url))
        gc.collect()
    except PermissionError as exc:
        log("Sertifika yetki hatası: {}".format(exc))
        # PDF aktarımı başlamadıysa tarayıcıya anlamlı HTTP hatası döndür.
        try:
            json_response(client, "401 Unauthorized", {"ok": False, "error": str(exc)})
        except Exception:
            pass
    except Exception as exc:
        log("Sertifika indirme hatası: {}".format(exc))
        try:
            json_response(client, "502 Bad Gateway", {"ok": False, "error": "Sertifika indirilemedi: {}".format(exc)})
        except Exception:
            pass
    finally:
        if response is not None:
            try:
                response.close()
            except Exception:
                pass
        gc.collect()


def unread_count():
    return _unread_changes

def api_state():
    return {
        "running": monitor_state.get("running", False),
        "waiting_login": monitor_state.get(
            "waiting_login",
            False
        ),
        "last_check": monitor_state.get("last_check"),
        "next_check": monitor_state.get("next_check"),
        "last_error": monitor_state.get("last_error"),
        "total_applications": monitor_state.get(
            "total_applications",
            0
        ),
        "total_programs": monitor_state.get(
            "total_programs",
            0
        ),
        "started_at": monitor_state.get("started_at"),
        "check_interval": CHECK_INTERVAL,
        "min_check_interval": MIN_CHECK_INTERVAL,
        "max_check_interval": MAX_CHECK_INTERVAL,
        "unread_changes": _unread_changes,
        "stats": monitor_state.get(
            "stats",
            {
                "success": 0,
                "fail": 0,
                "appeal": 0,
                "evaluation": 0,
                "winner": 0,
                "applied": 0,
            }
        ),
        "free_ram": gc.mem_free(),
        "next_check_delay": monitor_state.get(
            "next_check_delay",
            CHECK_INTERVAL
        ),
        "current_year": time.localtime(time.time())[0],
    }

def api_settings():
    profiles = []

    for item in settings.get("wifi_profiles", []):
        if not isinstance(item, dict):
            continue

        # PAROLALAR ASLA HTTP cevabına konulmaz.
        profiles.append({
            "ssid": str(item.get("ssid", "")),
            "password_configured": bool(item.get("password", "")),
        })

    return {
        "wifi_profiles": profiles,
        "t3_email": settings.get("t3_email", ""),
        "t3_password_configured": bool(settings.get("t3_password", "")),
        "check_interval": CHECK_INTERVAL,
        "min_check_interval": MIN_CHECK_INTERVAL,
        "max_check_interval": MAX_CHECK_INTERVAL,
    }

def sanitize_web_settings(payload):
    # Web arayüzü sadece yeni parola girilmişse parolayı kabul eder.
    # Boş parola alanları mevcut gizli değeri KORUR.
    if not isinstance(payload, dict):
        return {}

    data = {}
    for key in ("check_interval", "min_check_interval", "max_check_interval", "t3_email"):
        if key in payload:
            data[key] = payload.get(key)

    if "t3_password" in payload and str(payload.get("t3_password") or ""):
        data["t3_password"] = str(payload.get("t3_password"))

    if "wifi_profiles" in payload and isinstance(payload.get("wifi_profiles"), list):
        old_profiles = settings.get("wifi_profiles", [])
        old_by_ssid = {}
        for item in old_profiles:
            if isinstance(item, dict):
                old_by_ssid[str(item.get("ssid", "")).strip()] = str(item.get("password", ""))

        profiles = []
        for item in payload.get("wifi_profiles", []):
            if not isinstance(item, dict):
                continue
            ssid = str(item.get("ssid", "")).strip()
            if not ssid:
                continue
            incoming = str(item.get("password", "") or "")
            profiles.append({
                "ssid": ssid,
                "password": incoming if incoming else old_by_ssid.get(ssid, ""),
            })
        data["wifi_profiles"] = profiles

    return data

def mark_one_read(change_id):
    global _unread_changes

    changes = load_changes()
    new_changes = []
    changed = False

    for item in changes:
        if str(item.get("id")) == str(change_id):
            # Tıklanan öğeyi bulduk, alarm sayacını düşür.
            if not item.get("read", False):
                if _unread_changes > 0:
                    _unread_changes -= 1
            changed = True
            # ÖNEMLİ: Bu öğeyi 'new_changes' listesine eklemiyoruz, yani siliyoruz.
        else:
            # Sistemde geçmişten kalmış, "okundu" işaretli ama 
            # dosyadan silinmemiş çöp kayıtlar varsa onları da temizle.
            if item.get("read", False):
                changed = True 
            else:
                new_changes.append(item)

    if changed:
        save_changes(new_changes)

    del changes
    del new_changes
    gc.collect()

    # Kalan okunmamış kayıt varsa alarm yeşil kalır; son kayıt da okunmuşsa söner.
    if _unread_changes > 0:
        led_start_alert()
    else:
        led_stop_alert()

    return {"ok": True}

def mark_all_read():
    global _unread_changes

    # Tüm değişiklikleri tamamen temizle: değişiklikler dosyasını sil.
    try:
        import os
        try:
            os.remove(CHANGES_FILE)
            log("Değişiklikler dosyası silindi: {}".format(CHANGES_FILE))
        except OSError:
            # Dosya zaten yoksa başarılı kabul edilir.
            pass
    except Exception as exc:
        log("Değişiklikler dosyası silme API hatası: {}".format(exc))

    _unread_changes = 0
    gc.collect()
    led_stop_alert()

    return {"ok": True, "unread_changes": 0}

# ============================================================
# MİNİ HTTP SERVER
# ============================================================

def start_web_server():
    server = socket.socket()

    try:
        server.setsockopt(
            socket.SOL_SOCKET,
            socket.SO_REUSEADDR,
            1
        )
    except Exception:
        pass

    server.bind(("0.0.0.0", WEB_PORT))
    server.listen(4)

    # Non-blocking.
    try:
        server.setblocking(False)
    except Exception:
        pass

    log("Dashboard portu: {}".format(WEB_PORT))

    return server

def parse_request(request):
    try:
        line = request.split(b"\r\n", 1)[0].decode()
        parts = line.split(" ")

        if len(parts) < 2:
            return "GET", "/"

        return parts[0], parts[1]

    except Exception:
        return "GET", "/"

def read_request_body(client, initial):
    header_end = initial.find(b"\r\n\r\n")

    if header_end < 0:
        return b""

    body = initial[header_end + 4:]

    header_part = initial[:header_end].decode(
        "utf-8",
        "ignore"
    )

    content_length = 0

    for line in header_part.split("\r\n"):
        if ":" not in line:
            continue

        name, value = line.split(":", 1)

        if name.strip().lower() != "content-length":
            continue

        try:
            content_length = int(value.strip())
        except Exception:
            content_length = 0

        break

    if content_length <= len(body):
        return body[:content_length]

    remaining = content_length - len(body)
    chunks = [body]

    while remaining > 0:
        chunk = client.recv(
            min(1024, remaining)
        )

        if not chunk:
            break

        chunks.append(chunk)
        remaining -= len(chunk)

    return b"".join(chunks)

def request_json_body(client, initial):
    body = read_request_body(client, initial)

    if not body:
        return {}

    try:
        data = ujson.loads(
            body.decode("utf-8")
        )
        return data if isinstance(data, dict) else {}
    finally:
        del body
        gc.collect()

def handle_client(client):
    try:
        client.settimeout(3)

        # Request buffer'ını gereğinden büyük tutmuyoruz.
        raw = client.recv(4096)

        if not raw:
            return

        method, path = parse_request(raw)

        # Ana dashboard.
        if method == "GET" and path == "/":
            del raw
            html_response(
                client,
                "200 OK"
            )
            return

        # API state: küçük endpoint, normal JSON.
        if method == "GET" and path == "/api/state":
            del raw
            json_response(
                client,
                "200 OK",
                api_state()
            )
            return

        # Büyük endpoint'ler artık Flash'tan doğrudan stream ediliyor.
        if method == "GET" and path == "/api/changes":
            del raw
            file_json_response(
                client,
                "200 OK",
                CHANGES_FILE
            )
            return

        if method == "GET" and path == "/api/competitions":
            del raw
            file_json_response(
                client,
                "200 OK",
                COMPETITIONS_FILE
            )
            return

        if method == "GET" and path == "/api/applications":
            del raw
            file_json_response(
                client,
                "200 OK",
                APPLICATIONS_FILE
            )
            return

        if method == "GET" and path == "/api/certificates":
            del raw
            json_response(
                client,
                "200 OK",
                api_certificates()
            )
            return

        if method == "GET" and path.startswith("/api/certificates/download/"):
            certificate_id = path.rsplit("/", 1)[-1].strip()
            del raw
            log("Sertifika indirme isteği: {}".format(certificate_id))
            certificate_download_response(client, certificate_id)
            return

        if method == "POST" and path == "/api/certificates/hide":
            payload = request_json_body(client, raw)
            del raw
            result = hide_certificate(payload.get("id", ""))
            json_response(
                client,
                "200 OK" if result.get("ok") else "400 Bad Request",
                result
            )
            del payload
            gc.collect()
            return

        if method == "POST" and path == "/api/certificates/restore":
            payload = request_json_body(client, raw)
            del raw
            result = restore_certificate(payload.get("id", ""))
            json_response(
                client,
                "200 OK" if result.get("ok") else "400 Bad Request",
                result
            )
            del payload
            gc.collect()
            return

        if method == "GET" and path.startswith("/api/competition-detail/"):
            record_id = path.rsplit("/", 1)[-1].strip()
            details = load_competition_details()
            result = None
            competitions = load_json(COMPETITIONS_FILE, [])
            if isinstance(competitions, list):
                for competition in competitions:
                    ids = competition.get("ids", []) if isinstance(competition, dict) else []
                    if record_id in [str(x) for x in ids]:
                        program = clean_html(competition.get("program"))
                        result = details.get(program)
                        if result is None:
                            try:
                                result = fetch_competition_detail(record_id, program)
                                details[program] = result
                                save_competition_details(details)
                            except Exception as exc:
                                json_response(client, "500 Internal Server Error", {"ok": False, "error": str(exc)})
                                return
                        break
            del details
            del competitions
            gc.collect()
            if result is None:
                json_response(client, "404 Not Found", {"ok": False, "error": "Yarışma detayı bulunamadı."})
            else:
                json_response(client, "200 OK", result)
            return

        if method == "POST" and path.startswith("/api/competition-detail/") and path.endswith("/refresh"):
            record_id = path[len("/api/competition-detail/"):-len("/refresh")].strip("/")
            try:
                result = refresh_one_competition_detail(record_id)
                json_response(client, "200 OK", {"ok": True, "detail": result})
            except Exception as exc:
                json_response(client, "500 Internal Server Error", {"ok": False, "error": str(exc)})
            return

        if method == "GET" and path == "/api/settings":
            del raw
            json_response(
                client,
                "200 OK",
                api_settings()
            )
            return

        if method == "POST" and path == "/api/settings":
            payload = request_json_body(
                client,
                raw
            )
            del raw

            safe_payload = sanitize_web_settings(payload)
            del payload

            result = apply_settings(
                safe_payload,
                immediate=True
            )
            del safe_payload

            json_response(
                client,
                "200 OK",
                result
            )

            del payload
            gc.collect()
            return

        if method == "POST" and path == "/api/update-now":
            del raw
            monitor_state["force_check"] = True
            monitor_state["next_check"] = time.time()
            monitor_state["next_check_delay"] = 0
            save_monitor_state()

            json_response(
                client,
                "200 OK",
                {
                    "ok": True,
                    "message": "Güncelleme sıraya alındı."
                }
            )
            return

        # POST /api/changes/read-all
        if (
            method == "POST"
            and path == "/api/changes/read-all"
        ):
            del raw
            json_response(
                client,
                "200 OK",
                mark_all_read()
            )
            return

        # POST /api/changes/<id>/read
        prefix = "/api/changes/"
        suffix = "/read"

        if (
            method == "POST"
            and path.startswith(prefix)
            and path.endswith(suffix)
        ):
            del raw
            change_id = path[
                len(prefix):-len(suffix)
            ]

            change_id = change_id.replace(
                "%20",
                " "
            )

            json_response(
                client,
                "200 OK",
                mark_one_read(change_id)
            )
            return

        del raw
        html_response(
            client,
            "404 Not Found"
        )

    except Exception as exc:
        log("Dashboard istemci hatası: {}".format(exc))

        try:
            json_response(
                client,
                "500 Internal Server Error",
                {
                    "ok": False,
                    "error": str(exc),
                }
            )
        except Exception:
            pass

    finally:
        try:
            client.close()
        except Exception:
            pass

        gc.collect()

def poll_web_server():
    if web_server is None:
        return

    try:
        client, address = web_server.accept()
    except Exception:
        return

    # Her ana döngü turunda en fazla bir istemci işle; tarayıcının
    # speculative/half-open bağlantısı monitor döngüsünü bloklamasın.
    handle_client(client)

# ============================================================
# WIFI
# ============================================================

def _reset_wlan(wlan):
    # ESP32-S3'te bazen STA arayüzü geçersiz bir iç duruma girebiliyor.
    # Bir sonraki SSID denemesine temiz bir WLAN nesnesiyle başla.
    if wlan is not None:
        try:
            wlan.disconnect()
        except Exception:
            pass
        try:
            wlan.active(False)
        except Exception:
            pass
    del wlan
    gc.collect()

def wifi_connect():
    """
    ESP32-S3 / MicroPython için RAM dostu çoklu Wi-Fi profil bağlantısı.
    Her SSID kendi parolasıyla ayrı bir profil olarak denenir.
    """
    if not WIFI_PROFILES:
        raise RuntimeError("WIFI_PROFILES listesi boş.")

    gc.collect()

    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    try:
        wlan.config(reconnects=5)
    except Exception:
        pass

    try:
        if wlan.isconnected():
            log(
                "Wi-Fi zaten bağlı (IP: {} )".format(
                    wlan.ifconfig()[0]
                )
            )
            return wlan
    except Exception:
        pass

    last_error = None

    for index, profile in enumerate(WIFI_PROFILES):
        ssid = str(profile.get("ssid", "")).strip()
        password = str(profile.get("password", ""))

        if not ssid:
            continue

        try:
            try:
                wlan.disconnect()
            except Exception:
                pass

            gc.collect()

            log(
                "Wi-Fi bağlanıyor: {} ({}/{})".format(
                    ssid,
                    index + 1,
                    len(WIFI_PROFILES)
                )
            )

            wlan.connect(ssid, password)

            deadline = time.ticks_add(
                time.ticks_ms(),
                20000
            )

            while not wlan.isconnected():
                poll_web_server()

                if time.ticks_diff(
                    deadline,
                    time.ticks_ms()
                ) <= 0:
                    raise RuntimeError(
                        "Wi-Fi bağlantı timeout: {}".format(ssid)
                    )

                time.sleep_ms(250)

            log(
                "Wi-Fi Bağlandı (SSID: {} / IP: {} )".format(
                    ssid,
                    wlan.ifconfig()[0]
                )
            )

            gc.collect()
            return wlan

        except Exception as exc:
            last_error = exc
            log(
                "Wi-Fi {} başarısız: {}".format(
                    ssid,
                    exc
                )
            )

            try:
                wlan.disconnect()
            except Exception:
                pass

            gc.collect()
            time.sleep_ms(300)

    raise RuntimeError(
        "Hiçbir Wi-Fi ağına bağlanılamadı. Son hata: {}".format(
            last_error
        )
    )

def sync_time():
    # TLS için doğru saat önemli.
    try:
        import ntptime
        ntptime.settime()
        log("NTP senkronizasyonu başarılı.")
    except Exception as exc:
        log("NTP uyarısı: {}".format(exc))

# ============================================================
# MONITOR / HATA TOLERANSI
# ============================================================

def initialize_unread_count():
    global _unread_changes

    changes = load_changes()

    _unread_changes = sum(
        1
        for item in changes
        if not item.get("read", False)
    )

    del changes
    gc.collect()

    # Yeniden başlatmada okunmamış değişiklik varsa alarmı yeniden yak.
    if _unread_changes > 0:
        led_start_alert()
    else:
        led_stop_alert()

def do_login_and_check():
    global http_session

    monitor_state["waiting_login"] = True
    monitor_state["running"] = False
    save_monitor_state()

    t3_login()
    led_set_login(False)

    monitor_state["waiting_login"] = False
    monitor_state["running"] = True
    save_monitor_state()

    return perform_check()

def main():
    global web_server
    global http_session

    load_all_state()

    if not WIFI_PROFILES:
        raise RuntimeError(
            "Wi-Fi profili tanımlanmamış. Dashboard veya main.py ile WIFI_PROFILES doldur."
        )

    if not T3_EMAIL or not T3_PASSWORD:
        raise RuntimeError(
            "T3 kullanıcı adı ve parola tanımlanmamış."
        )

    log("KYS Monitor / ESP32-S3 v2026.08.23-v9 başlıyor.")
    log("RAM: {} bytes".format(free_ram()))

    led_init()
    initialize_unread_count()

    monitor_state["started_at"] = None
    monitor_state["running"] = False
    monitor_state["waiting_login"] = True
    save_monitor_state()

    wlan = wifi_connect()
    sync_time()

    # NTP sonrasında mevcut Flash önbelleğini güncel sınıflandırma ile
    # yeniden oluştur. Böylece yeni kurallar için ayrıca bir check beklenmez.
    rebuild_cached_classification()

    # NTP sonrasında kaydet; böylece web panelinde gerçek başlangıç zamanı
    # "-" veya 2000-01-01 benzeri hatalı zaman olarak görünmez.
    monitor_state["started_at"] = time.time()
    save_monitor_state()

    web_server = start_web_server()

    # Sınıflandırma NTP sonrasında bir kez yenilendi; dashboard aynı önbelleği kullanır.

    # --------------------------------------------------------
    # İlk login + ilk tarama
    # --------------------------------------------------------

    backoff = 5

    while True:

        try:
            if not wlan.isconnected():
                wlan = wifi_connect()
                sync_time()

            result = do_login_and_check()

            log(
                "İlk kontrol: {} kayıt / {} program".format(
                    result["records"],
                    result["programs"]
                )
            )

            backoff = 5
            break

        except Exception as exc:

            monitor_state["running"] = False
            monitor_state["last_error"] = str(exc)
            led_set_error(True)
            save_monitor_state()

            log(
                "Başlangıç hatası [{}]: {}".format(
                    type(exc).__name__,
                    exc
                )
            )

            for _ in range(backoff):
                poll_web_server()
                time.sleep(1)

            backoff = min(
                backoff * 2,
                900
            )

    # --------------------------------------------------------
    # Sürekli çalışma
    # --------------------------------------------------------

    delay = schedule_next_check()
    next_check_ms = time.ticks_add(
        time.ticks_ms(),
        int(delay * 1000)
    )

    backoff = 5

    while True:

        led_refresh_alert()

        # Dashboard'u sürekli canlı tut.
        poll_web_server()

        led_refresh_alert()

        # Watchdog.
        try:
            if wdt is not None:
                wdt.feed()
        except Exception:
            pass

        # Dashboard üzerinden Wi-Fi profilleri değiştirildiyse bağlantıyı yenile.
        if monitor_state.get("force_reconnect", False):
            try:
                monitor_state["force_reconnect"] = False

                try:
                    wlan.disconnect()
                except Exception:
                    pass

                wlan = wifi_connect()
                sync_time()

                http_session = None
                monitor_state["force_relogin"] = True
                monitor_state["running"] = False
                monitor_state["last_error"] = None
                save_monitor_state()

            except Exception as exc:
                monitor_state["last_error"] = str(exc)
                monitor_state["running"] = False
                led_set_error(True)
                save_monitor_state()

        # Wi-Fi koptuysa yeniden bağlan.
        if not wlan.isconnected():

            log("Wi-Fi koptu.")

            monitor_state["running"] = False
            monitor_state["last_error"] = "Wi-Fi bağlantısı koptu."
            led_set_error(True)
            save_monitor_state()

            try:
                wlan = wifi_connect()
                sync_time()

                http_session = None

                result = do_login_and_check()

                log(
                    "Bağlantı sonrası kontrol: {} kayıt".format(
                        result["records"]
                    )
                )

                backoff = 5

                delay = schedule_next_check()
                next_check_ms = time.ticks_add(
                    time.ticks_ms(),
                    int(delay * 1000)
                )

            except Exception as exc:
                log(
                    "Wi-Fi yeniden bağlanma hatası: {}".format(
                        exc
                    )
                )

                monitor_state["last_error"] = str(exc)
                save_monitor_state()

                time.sleep(backoff)

                backoff = min(
                    backoff * 2,
                    900
                )

            continue

        force_check_now = monitor_state.get("force_check", False)
        
        # Dashboard "Şimdi Güncelle" dediğinde zamanlayıcıyı bekleme.
        if force_check_now:
            next_check_ms = time.ticks_ms()

        # Ayarlar kullanıcı adı/parola değiştirdiyse yeni HTTP oturumu aç.
        if monitor_state.get("force_relogin", False):
            monitor_state["force_relogin"] = False
            http_session = None

        # Kontrol zamanı geldi mi?
        if force_check_now or time.ticks_diff(
            time.ticks_ms(),
            next_check_ms
        ) >= 0:

            try:

                # Oturum bozulmuşsa tekrar login gerekebilir.
                if (
                    http_session is None
                    or not http_session.logged_in
                ):
                    t3_login()

                result = perform_check()
                monitor_state["force_check"] = False

                log(
                    "Kontrol: {} kayıt / {} program / {} değişiklik".format(
                        result["records"],
                        result["programs"],
                        result["changes"]
                    )
                )

                backoff = 5

                delay = schedule_next_check()
                next_check_ms = time.ticks_add(
                    time.ticks_ms(),
                    int(delay * 1000)
                )

            except PermissionError as exc:
                monitor_state["force_check"] = False

                log("Session reddedildi: {}".format(exc))

                try:
                    t3_login()
                    result = perform_check()

                    backoff = 5

                    delay = schedule_next_check()
                    next_check_ms = time.ticks_add(
                        time.ticks_ms(),
                        int(delay * 1000)
                    )

                except Exception as relogin_error:

                    monitor_state["running"] = False
                    monitor_state["last_error"] = str(
                        relogin_error
                    )
                    save_monitor_state()

                    log(
                        "Yeniden login başarısız: {}".format(
                            relogin_error
                        )
                    )

                    time.sleep(backoff)
                    backoff = min(
                        backoff * 2,
                        900
                    )

            except Exception as exc:
                monitor_state["force_check"] = False

                monitor_state["last_error"] = str(exc)
                monitor_state["running"] = False
                save_monitor_state()

                log(
                    "Kontrol hatası [{}]: {}".format(
                        type(exc).__name__,
                        exc
                    )
                )

                # Bir sonraki denemeyi kısa backoff ile yap.
                time.sleep(backoff)

                backoff = min(
                    backoff * 2,
                    900
                )

                delay = max(
                    30,
                    min(900, backoff)
                )
                next_check_ms = time.ticks_add(
                    time.ticks_ms(),
                    int(delay * 1000)
                )

        else:
            # CPU'yu boş yere döndürme.
            time.sleep_ms(100)

        gc.collect()

# ============================================================
# WATCHDOG
# ============================================================

wdt = None
"""
if machine is not None:

    try:
        wdt = machine.WDT(
            timeout=120000
        )
        log("Watchdog aktif.")
    except Exception as exc:
        log("Watchdog kullanılamıyor: {}".format(exc))

"""
# ============================================================
# START
# ============================================================

main()
