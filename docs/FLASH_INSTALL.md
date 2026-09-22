# ESP32-S3 Flash Kurulumu

Aşağıdaki komutlar proje geliştirme sırasında kullanılan örnektir. Seri port ve firmware dosyası kendi cihazınıza göre değiştirilmelidir.

```bash
esptool.py --chip esp32s3 --port /dev/ttyACM0 erase_flash
esptool.py --chip esp32s3 --port /dev/ttyACM0 --baud 460800 write_flash -z 0x0 ESP32_GENERIC_S3-SPIRAM_OCT-20260818-v1.29.0-preview.731.g1c3c201149.bin
```

Ardından:

1. Wi-Fi ve T3 KYS kullanıcı bilgilerini yapılandırın.
2. `main.py` dosyasını karta `main.py` adıyla yükleyin.
3. `index.html` dosyasını karta `index.html` adıyla yükleyin.
4. Cihazı yeniden başlatın.
5. İlk açılışta yarışma detayları da alındığı için başlangıç taraması daha uzun sürebilir.
6. Cihazın aldığı IP adresinden dashboard'a bağlanın.

### Uyarılar

- Gerçek Wi-Fi/T3 KYS parolalarını GitHub'a yüklemeyin.
- Dashboard'u internet üzerinden erişilebilir hâle getirmeyin.
- Dahili RGB LED sürücüsü kart/LED davranışına duyarlıdır ve LED'e zarar verebilir.
- Çalışma sırasında Flash dosya sistemine yazmalar yapılır; yoğun kullanım Flash ömrünü azaltabilir.
- Yazılımın kullanımı tamamen kullanıcının kendi risk ve sorumluluğundadır.
