# Kurulum

## Gereksinimler

- ESP32-S3 DevKit v1.3
- USB bağlantısı
- `esptool`
- MicroPython
- `main.py` ve `index.html` dosyalarını karta yüklemek için Thonny veya benzeri bir araç

## 1. Flash belleği temizleyin

ESP32-S3'ü USB üzerinden bilgisayara bağlayın ve seri portunuzu belirleyin. Ardından Flash belleği silin:

```bash
esptool.py --chip esp32s3 --port /dev/ttyACM0 erase_flash
```

`/dev/ttyACM0` kısmını kendi seri portunuzla değiştirin.

## 2. MicroPython yükleyin

MicroPython firmware'ini karta yazın:

```bash
esptool.py --chip esp32s3 --port /dev/ttyACM0 --baud 460800 write_flash -z 0x0 ESP32_GENERIC_S3-SPIRAM_OCT-20260818-v1.29.0-preview.731.g1c3c201149.bin
```

Firmware dosyasının adını ve seri portu kendi kurulumunuza göre değiştirin.

## 3. `main.py` dosyasını yapılandırın

`main.py` dosyasını karta yüklemeden önce dosyanın başındaki Wi-Fi ve T3 KYS hesap bilgilerini düzenleyin:

```python
WIFI_PROFILES = [
    {
        "ssid": "WiFi_ADI",
        "password": "WiFi_SIFRE"
    }
]

T3_EMAIL = "T3_KYS_KULLANICI_ADI_VEYA_EPOSTA"
T3_PASSWORD = "T3_KYS_SIFRE"
```

`WIFI_PROFILES` bölümüne kullanılacak Wi-Fi ağını ve parolasını girin.

Birden fazla ağ kullanılacaksa listeye ek profiller ekleyebilirsiniz:

```python
WIFI_PROFILES = [
    {
        "ssid": "EvWiFi",
        "password": "EvWiFi_Sifresi"
    },
    {
        "ssid": "TelefonHotspot",
        "password": "Hotspot_Sifresi"
    }
]
```

`T3_EMAIL` alanına T3 KYS hesabınızın kullanıcı adı veya e-posta bilgisini, `T3_PASSWORD` alanına hesabınızın parolasını girin.

Bu bilgiler tanımlanmadan uygulama başlatılmaz.

## 4. Dosyaları karta yükleyin

ESP32-S3'e aşağıdaki iki dosyayı **aynı dosya adlarıyla** yükleyin:

```text
main.py
index.html
```

Dosyaları yükledikten sonra kartı yeniden başlatın.

## 5. Dashboard'u açın

Kart Wi-Fi ağına bağlandıktan sonra cihazın yerel IP adresini bulun ve tarayıcıdan açın:

```text
http://CIHAZ_IP_ADRESI/
```

İlk açılışta yarışma ayrıntıları alınacağı için başlangıç taraması normalden uzun sürebilir.

## 6. Ayarları dashboard üzerinden yönetin

Dashboard'un ayarlar bölümünden aşağıdaki değerleri daha sonra değiştirebilirsiniz:

- Wi-Fi profilleri
- T3 KYS kullanıcı adı/e-posta
- T3 KYS parolası
- Normal kontrol aralığı
- Minimum kontrol aralığı
- Maksimum kontrol aralığı

Ayarlar cihazın yerel Flash dosya sisteminde saklanır.

## Önemli notlar

- Uygulamayı yalnızca güvendiğiniz yerel ağlarda çalıştırın.
- Dashboard için ayrı bir web giriş ekranı bulunmaz.
- `main.py` ve `index.html` dosyalarını karta yüklemeden önce dosya adlarının değiştirilmediğinden emin olun.
- Cihazın yerel Flash belleğine ayar ve uygulama verileri yazılır. Gereksiz yazma işlemlerinden kaçının.
- T3 KYS hesap bilgilerini ve Wi-Fi bilgilerini güvenli tutun.
