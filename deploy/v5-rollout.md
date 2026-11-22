# AniVrum V5 chiqarish rejasi

## Telegram profili

@BotFather → `/mybots` → `@AniVrum_bot` → `Edit Bot` orqali quyidagi qiymatlarni kiriting.

| BotFather sozlamasi | Qiymat |
| --- | --- |
| Edit Name | 🎬 ANIVRUM \| ANIME |
| Edit About | 🎬 AniVrum — anime, fasllar, filmlar va OVA. Nom yoki kod orqali qidiring. |
| Edit Description | Quyidagi matn |
| Edit Botpic | AniVrum logotipining kvadrat nusxasi |
| Edit Description Picture | AniVrum logotipi va brendi tushirilgan gorizontal rasm |

```text
🌌 Anime olamiga xush kelibsiz!

🔥 Sevimli animelaringizni toping.
📺 Fasllar va qismlarni tanlang.
🎞 Filmlar va OVAlarni kashf eting.
🔎 Anime nomi yoki kodi orqali qidiring.

🚀 AniVrum — anime olamingiz bir joyda!
```

Repo va `assets/` papkasida logotip fayli topilmadi. Profil va tavsif rasmlari uchun AniVrum’ning asl logotipi kerak. [Telegram BotFather qo‘llanmasi](https://core.telegram.org/bots/features#about-text-description-and-profile-media)

Telegram inline tugmalari yashil, qizil va ko‘k uslublarni qo‘llaydi. OVA va qo‘shimcha amallar emoji bilan ajratiladi. [Telegram inline tugma uslublari](https://core.telegram.org/bots/api#inlinekeyboardbutton)

## Neon va Render

1. Neon Dashboard’da production branch, bevosita endpoint va tiklash nuqtasini tekshiring. Chiqarish lokal sinovlar va production’da faqat o‘qish rejimidagi sxema tekshiruviga tayanadi.
2. Migratsiya tasdiqlangach, quyidagi PowerShell blokini ishlating. Endpoint sifatida Neon Dashboard’dan tasdiqlangan production hostini kiriting. URL sifatida shu branchning pooling o‘chirilgan ulanish satridan foydalaning.

```powershell
Set-Location 'D:\AniVrum'
$python = '.\.venv\Scripts\python.exe'
$env:ANIVRUM_PRODUCTION_NEON_ENDPOINT = Read-Host 'Neon production host'
$neonSecret = Read-Host 'Neon production connection URL' -AsSecureString
try {
    $env:ANIVRUM_PRODUCTION_NEON_URL = [System.Net.NetworkCredential]::new('', $neonSecret).Password
    & $python -B -m database.migrate_catalog_layout --check
    if ($LASTEXITCODE -ne 0) { throw 'Neon tekshiruvi muvaffaqiyatsiz.' }
    & $python -B -m database.migrate_catalog_layout --apply
    if ($LASTEXITCODE -ne 0) { throw 'Migratsiya muvaffaqiyatsiz.' }
    & $python -B -m database.migrate_catalog_layout --check
    if ($LASTEXITCODE -ne 0) { throw 'Migratsiyadan keyingi tekshiruv muvaffaqiyatsiz.' }
} finally {
    Remove-Item Env:ANIVRUM_PRODUCTION_NEON_URL, Env:ANIVRUM_PRODUCTION_NEON_ENDPOINT -ErrorAction SilentlyContinue
    $neonSecret.Dispose()
}
```

3. Migratsiya mavjud katalogga beshta bo‘sh ustun, tashqi kalit va indeks qo‘shadi. DDL bitta tranzaksiyada bajariladi. Qayta bajarilganda to‘liq sxema tekshiriladi. Qisman yoki mos kelmaydigan sxema xato bilan qaytadi. GitHub pushdan oldin Render’dagi repo va branch, Auto-Deploy holati, start buyrug‘i, polling va production Neon ulanishini tekshiring.
4. Push va deploy tasdiqlangach, quyidagi buyruqlarni ishlating. Render Auto-Deploy yoqilgan bo‘lsa, push deployni boshlashi mumkin.

```powershell
Set-Location 'D:\AniVrum'
if ((git branch --show-current) -ne 'main') { throw 'Joriy branch main emas.' }
git fetch origin main
if ($LASTEXITCODE -ne 0) { throw 'GitHub main holati tekshirilmadi.' }
if ((git rev-parse HEAD) -ne (git rev-parse FETCH_HEAD)) { throw 'Lokal main GitHub main bilan mos emas.' }
$v5 = @(
    'bot/content.py', 'bot/extras.py', 'bot/main.py',
    'database/catalog.py', 'database/db.py', 'database/postgres.py',
    'database/catalog_layout.sql', 'database/migrate_catalog_layout.py',
    'tests/test_anivrum.py', 'tests/test_postgres.py', 'deploy/v5-rollout.md'
)
git add -- $v5
if ($LASTEXITCODE -ne 0) { throw 'V5 fayllarini staging qilish muvaffaqiyatsiz.' }
git diff --cached --check -- $v5
if ($LASTEXITCODE -ne 0) { throw 'V5 diff tekshiruvi muvaffaqiyatsiz.' }
git commit --only -m 'Release AniVrum V5' -- $v5
if ($LASTEXITCODE -ne 0) { throw 'Commit muvaffaqiyatsiz.' }
git push origin HEAD:refs/heads/main
```

5. Render’dagi jonli commit SHA, loglar, `/healthz`, katalog va video yuborilishini tekshiring. Kanal postlarini **Admin → Kanal → E’lonlar va postni yangilash** bo‘limida mavjud IDlari bilan yangilang.
6. Deployda muammo chiqsa, oldingi Render commitiga qayting. Qo‘shimcha ustunlar rollback qilingan kod bilan mos keladi.
