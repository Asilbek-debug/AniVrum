# AniVrum | Anime

## Windows

Loyiha papkasidan ishga tushiring. Mahalliy muhitda `BOT_TOKEN` va Telegram’dagi raqamli `ADMIN_ID` ni muhit o‘zgaruvchilari yoki loyiha ildizidagi `.env` orqali kiriting. Token va zaxira nusxalarini shaxsiy saqlang. Bir token uchun bitta polling jarayoni ishlasin.

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m database.backup backups
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe -m bot.main
```

Birinchi ishga tushish SQLite sxemasini tranzaksiyada yangilaydi. Eski yozuvlar shu bazada qoladi. «Yangi animelar» avval yaratilgan vaqti ma’lum bo‘lgan yozuvlarni, so‘ng eski yozuvlarni ID bo‘yicha ko‘rsatadi. Statistikada muvaffaqiyatli video yuborishlar sanaladi.

## Kontent va kanal

1. `/admin` → **Anime qo‘shish**. Ma’lumotlarni kiriting va posterni rasm qilib yuboring.
2. Fasllar sonini kiriting. Har faslga video yoki video hujjatlarini yuboring va `/finish` buyrug‘idan foydalaning.
3. **E’lonni ko‘rib chiqish** tugmasida ma’lumotlarni tekshiring. Tarqatish huquqi bor kontent uchun **Tasdiqlash va e’lon qilish** tugmasini bosing. Bot `@AniVrum` kanaliga poster, ma’lumotlar va **Yuklab olish** tugmasini bitta foto-xabar qilib yuboradi. **Sozlamalar → Kanal huquqlarini tekshirish** orqali botning e’lon huquqlarini ko‘ring.
4. Yangi va yangilangan kanal e’lonlari `https://t.me/AniVrum_bot?start=animeid_23` shaklidagi havoladan foydalanadi. Bu yerda `23` anime ID’si. Eski `anime_1001` havolasi tarixiy yozuv orqali faqat asl animeni ochadi. Anime o‘chirilsa, uning havolasi yaroqsiz bo‘ladi va kodi yangi animega berilishi mumkin. Oddiy chatga kod yuborish joriy kod egasini ochadi. Obuna talab qilinsa, bot tekshiruvdan so‘ng so‘ralgan sahifani ochadi.
5. **Posterlar** bo‘limida posterni qo‘shish, almashtirish yoki o‘chirish mumkin. **E’lonlar** bo‘limida mavjud kanal postini yangilang yoki Telegram rad etgan postni qayta yuboring. Natija noma’lum bo‘lsa, avval kanalni oching. Post yuborilgan bo‘lsa, xabar ID sini kiriting. Kanalda post bo‘lmasa, qayta yuborishga ruxsat bering.
6. Anime boshqaruvida **📢 E’lon → 📤 Kanalga qayta yuborish** tugmasini bosing. Posterni va matnni ko‘rib, **Kanalga yuborish** yoki **Bekor qilish**ni tanlang. Tasdiqlash yangi post yaratadi, avvalgi post kanalda qoladi. Keyingi **E’lonni yangilash** amali oxirgi saqlangan postga qo‘llanadi.
7. Oddiy post uchun **/admin → 📤 Kanalga post yuborish → Matn / Rasm / Video** ni tanlang. Xabarni yuboring yoki rasm va videoni forward qiling. Izoh ixtiyoriy. Ko‘rib chiqishdan keyin **Kanalga joylash** tugmasini bosing.

### Telegram’dagi profil va kanal nomi

- **Bot profili.** `@BotFather` ga `/setname` yuboring, `@AniVrum_bot` ni tanlang va yangi nom sifatida **AniVrum | Anime** yuboring. [BotFather hujjati](https://core.telegram.org/bots/features#edit-bots).
- **Kanal nomi.** Telegram Desktop’da `@AniVrum` kanalini tahrirlash huquqi bor hisobdan oching. **⋮ → Manage Channel (Kanalni boshqarish)** bo‘limida kanal nomini **AniVrum | Anime** qilib saqlang. Ommaviy havola va username maydonlarini o‘z holida qoldiring. [Telegram kanal huquqlari](https://telegram.org/faq_channels/#q-what-can-administrators-do).

Kino yozuvlari SQLite’da o‘z turi bilan saqlanadi. Botning joriy katalogi, qidiruvi, sevimlilari va admin menyulari anime yozuvlarini ko‘rsatadi. Boshqa media turlarini keyinroq shu tur ajratmasi asosida qo‘shish mumkin.

### Telegram Desktop’da izohlarni yoqish

1. Kanal egasi hisobidan Telegram Desktop’da `@AniVrum` kanalini oching.
2. Yuqoridagi **⋮ → Manage Channel (Kanalni boshqarish) → Discussion (Muhokama)** ni oching.
3. **Add a Group** ni bosing, mavjud guruhni tanlang yoki shu oynadan yangi guruh yarating. Telegram ko‘rsatgan ulash tasdig‘ini bosing va sozlamalarni saqlang.
4. Ulangandan keyin inline tugmasiz kanal postini oching. Telegram post ostida **Leave a comment** tugmasini ko‘rsatadi. Tugma matni ilova tiliga bog‘liq. Izohlar ishlashi uchun muhokama guruhidagi avtomatik uzatilgan xabarni saqlang.

Anime e’lonining **📥 YUKLAB OLISH** tugmasi inline klaviatura orqali yuboriladi. Telegram bunday kanal postida **Leave a comment** tugmasini yashiradi. Bot API’da uni majburan ko‘rsatadigan parametr yo‘q. Haqiqiy izohlar uchun **AniVrum | Chat** guruhida e’lonning avtomatik uzatilgan nusxasini toping va uning muhokama mavzusini oching. Jonli tekshiruv uchun mavjud inline tugmasiz postdagi izohlarni, anime e’lonidagi yuklab olish tugmasini va guruhdagi aynan shu e’lon mavzusini solishtiring. [Telegram’dagi holat tavsifi](https://bugs.telegram.org/c/41803/2), [Bot API](https://core.telegram.org/bots/api#sendphoto).

Guruhni kanalga Telegram foydalanuvchisi ulaydi. Bot kanalga post yuborish uchun administrator huquqidan foydalanadi, izohlarni Telegram boshqaradi. [Telegram muhokama guruhlari](https://core.telegram.org/api/discussion), [guruh ulash metodi](https://core.telegram.org/method/channels.setdiscussiongroup).

Kanal postlari ulashilishi uchun kanal sozlamalaridagi **Restrict Saving Content** cheklovini o‘chirilgan holda saqlang. Bot oddiy foydalanuvchilarga yuboradigan anime medialariga Telegram’ning uzatish va saqlash cheklovini qo‘llaydi. Admin oladigan media va kanal postlari bu cheklovsiz yuboriladi. Bu Telegram ilovasidagi cheklov bo‘lib, mutlaq himoya bermaydi. [Telegram Bot API](https://core.telegram.org/bots/api#sendvideo).

## GitHub va Render Free sinovi

GitHub uchun repozitoriyni qo‘lda yarating yoki mavjud repozitoriydan foydalaning. Commitdan oldin `git status --short --ignored` va `git diff --cached --name-only` orqali fayllarni tekshiring. `.gitignore` muhit fayllari, kalitlar, SQLite, loglar va zaxiralarni chiqarib tashlaydi. Agar fayl avval commit qilingan bo‘lsa, uning Git tarixini alohida tekshiring. Token ilgari yuklangan bo‘lsa, BotFather orqali uni almashtiring.

Render Dashboard’da **New → Web Service** ni tanlang, GitHub repozitoriysini ulang va quyidagi sozlamalarni kiriting. Avtomatik joylashtirishni istamasangiz, **Auto-Deploy** ni o‘chiring.

| Sozlama | Qiymat |
| --- | --- |
| Runtime | Python |
| Instance Type | Free |
| Build Command | `python -m pip install -r requirements.txt` |
| Start Command | `python -m bot.web` |
| Health Check Path | `/healthz` |
| Python | `.python-version` orqali 3.14.10 |

| Muhit o‘zgaruvchisi | Sinovdagi qiymat yoki vazifasi |
| --- | --- |
| `ENABLE_BOT` | Avval `false` qoldiring. Faqat `true` qiymatida Telegram polling yoqiladi. |
| `PORT` | Render avtomatik beradi. Mahalliy standart qiymat `10000`. |
| `ANIVRUM_DB_PATH` | Ixtiyoriy, masalan `/tmp/anivrum-test.db`. Standart yo‘l tizimning vaqtinchalik papkasida. Render rejimi asosiy `database/anivrum.db` faylini qabul qilmaydi. |
| `BOT_TOKEN` | Polling yoqilganda, Render’ning **Environment** bo‘limiga sinov boti tokenini kiriting. |
| `ADMIN_ID` | Polling yoqilganda, administratorning raqamli Telegram ID’sini kiriting. |

`ENABLE_BOT=false` bo‘lsa, `GET /healthz` HTTP 200 qaytaradi. Polling, SQLite va Telegram sozlamalari ishga tushirilmaydi. Polling yoqilib, jarayon tugasa, endpoint HTTP 503 beradi. Bu endpoint Telegram bilan aloqani jonli tekshirmaydi. Mahalliy HTTP sinovi uchun `python -m bot.web` ni ishga tushirib, `http://localhost:10000/healthz` ni oching. Mavjud mahalliy polling buyrug‘i yuqoridagi **Windows** bo‘limida.

Render Free HTTP trafigi bo‘lmasa 15 daqiqada uyquga ketadi. Sinov SQLite bazasidagi o‘zgarishlar xizmat qayta ishga tushganda yoki yangi deploy qilinganda yo‘qolishi mumkin. Bu sozlama bepul sinov uchun. [Render Free](https://render.com/docs/free) · [Python versiyasi](https://render.com/docs/python-version) · [Web Service porti](https://render.com/docs/web-services#port-binding).

## Linux serverda 24/7

Python 3.14, systemd va `anivrum` xizmat foydalanuvchisiga ega serverga loyihani `/opt/anivrum` manziliga joylang. Mahalliy bot jarayonini to‘xtating va serverga SQLite zaxira nusxasini `/opt/anivrum/database/anivrum.db` sifatida ko‘chiring. Kodga xizmat foydalanuvchisi o‘qish, `database/` va `backups/` papkalariga yozish huquqiga ega bo‘lsin.

```sh
cd /opt/anivrum
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
sudo install -d -o anivrum -g anivrum -m 0700 /opt/anivrum/backups
sudoedit /etc/anivrum.env
sudo chmod 0600 /etc/anivrum.env
sudo cp deploy/anivrum.service deploy/anivrum-backup.service deploy/anivrum-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now anivrum.service anivrum-backup.timer
sudo systemctl start anivrum-backup.service
sudo journalctl -u anivrum.service -n 50
```

`/etc/anivrum.env` fayliga `BOT_TOKEN` va `ADMIN_ID` ni `NOM=qiymat` shaklida kiriting. Xizmat xatodan keyin qayta ishga tushadi. Kundalik zaxiralarni `/opt/anivrum/backups/` dan vaqti-vaqti bilan boshqa saqlash joyiga ko‘chiring. Tiklashda xizmatni to‘xtating, amaldagi bazani alohida saqlang, tekshirilgan zaxirani `database/anivrum.db` sifatida joylashtiring va xizmatni qayta ishga tushiring.

## Render Auto-Deploy sinovi

Bu commit GitHub orqali Render sinov servisida avtomatik deploy ishga tushishini tekshirish uchun yuboriladi.
