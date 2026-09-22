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

## 3. Wi-Fi bilgisini `main.py` içinde ayarlayın

`main.py` dosyasını karta yüklemeden önce dosyanın başındaki Wi-Fi ayarlarını kendi ağınıza göre düzenleyin:

```python
WIFI_PROFILES = [
    {"ssid": "WiFi_Adiniz", "password": "WiFi_Parolaniz"}
]
```

Wi-Fi bilgilerini doğrudan GitHub'a göndermeyin. Gerçek parolanızı içeren `main.py` dosyasını herkese açık bir repoya yüklemeyin.

## 4. Dosyaları karta yükleyin

ESP32-S3'e aşağıdaki iki dosyayı **aynı dosya adlarıyla** yükleyin:

```text
main.py
index.html
```

Dosyaları yükledikten sonra kartı yeniden başlatın.

## 5. Dashboard'u açın

Kart Wi-Fi ağına bağlandıktan sonra yerel IP adresini bulun ve tarayıcıdan açın:

```text
http://CIHAZ_IP_ADRESI/
```

İlk açılışta yarışma ayrıntıları alınacağı için başlangıç taraması normalden uzun sürebilir.

## 6. T3 KYS bilgilerini girin

Dashboard açıldıktan sonra ayarlar bölümünden T3 KYS kullanıcı adı/e-posta ve parolanızı girin. Ayarları kaydettikten sonra monitor bağlantıyı kullanarak T3 KYS hesabına giriş yapar.

T3 KYS parolanızı GitHub'a, ekran görüntülerine veya hata kayıtlarına eklemeyin.

## Önemli notlar

- Uygulamayı yalnızca güvendiğiniz yerel ağlarda çalıştırın. Dashboard için ayrı bir web giriş ekranı bulunmaz.
- `main.py` ve `index.html` dosyalarını karta yüklemeden önce dosya adlarının değiştirilmediğinden emin olun.
- Cihazın yerel Flash belleğine ayar ve uygulama verileri yazılır. Gereksiz yazma işlemlerinden kaçının.
- Gerçek Wi-Fi ve T3 KYS bilgilerini içeren dosyaları herkese açık depoya göndermeyin.
