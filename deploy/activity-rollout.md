# Foydalanuvchilar nazorati va production rejasi

Funksiya standart holatda o‘chiq. Bot egasi 30 kunlik saqlash muddatini
tasdiqlagan. Qayd xabarnomadan keyingi rozilik bilan boshlanadi.
Yaqindagi faollik chegarasi 5 daqiqa va faqat botdagi qaydga tegishli.

/start va /privacy orqali foydalanuvchi xabarnomani ko‘radi. Rozilik
tugmasidan keyingi qayd qilinadigan amallar uchun bitta oxirgi holat saqlanadi.
Eski statistika ushbu jadvalga ko‘chirilmaydi. /delete_activity shu ixtiyoriy
qaydni va rozilikni o‘chiradi. Kontent tanlovi o‘z qayd vaqtidan 30 kun
o‘tgach, butun holat esa oxirgi faollikdan 30 kun o‘tgach qidiruvdan chiqariladi.
Tozalash bot ishlaganda har 15 daqiqada bajariladi.
Muddat bot bazasidagi qaydlarga tegishli. Telegram’da egasiga avval
yuborilgan profil xabarlari bazadagi qayd o‘chirilganda avtomatik o‘chmaydi.

## Production oldidan tekshiruv

1. Render Dashboard’da production repo va branch’ni, Live commit SHA’sini,
   Auto-Deploy rejimini, start buyrug‘ini va polling sozlamasini tekshiring.
   Funksiya bayrog‘i sozlanmagan yoki false ekanini pushdan oldin
   tasdiqlang. Render DATABASE_URL aynan mo‘ljallangan Neon bazasi va
   branch’iga tegishli ekanini ulanish satrini oshkor qilmasdan tekshiring.
2. Neon Dashboard’da tiklash oynasi, maqsad bazasi va branch’ni, anivrum
   katalog versiyasi 4 ekanini hamda migratsiya rolining anivrum
   sxemasida jadval va indeks yaratish huquqlarini tekshiring. Zaxirani
   boshqa branch’ga tiklab yoki belgilangan vaqtdan alohida branch yaratib,
   u yerdan o‘qishni tekshiring. Zaxira IDsi yoki tiklash vaqti, branch
   va natijani qayd eting. Tiklash sinovini asosiy branch’da bajarmang.
3. Tiklangan ajratilgan branch’da migratsiyani ikki marta bajaring. Anime,
   fasl, qism, media file_id, e’lon va eski foydalanuvchi yozuvlarining
   migratsiya oldi va keyingi sonlari hamda asosiy qiymatlarini solishtiring.
   Render’dagi aniq Live commit bilan katalog sxemasi va asosiy o‘qish
   yo‘llarini migratsiyadan keyin qayta tekshiring. Test polling ishlatilsa,
   alohida bot tokenini qo‘llang. Tekshiruv xato bersa, chiqarishni to‘xtating.

## Chiqarish tartibi

1. Alohida ruxsatdan keyin tayyor commitni GitHub’ga yuboring. Render
   Auto-Deploy ulangan bo‘lsa, push deployni boshlashi mumkin. Birinchi
   deployda ANIVRUM_ACTIVITY_ENABLED=false yoki sozlanmagan bo‘lsin.
   Shu holatda yangi jadval yaratilmaydi va yangi qayd boshlanmaydi.
2. Render Deploys bo‘limida yangi SHA Live ekanini, loglarni, /healthz
   javobini va katalogdan oddiy foydalanishni tekshiring. Startup’da
   avvaldan mavjud statistikani tozalash amali ishlaydi. Statistik
   yozuvlarning odatiy muddat bo‘yicha ham o‘chishi mumkin bo‘lmagan
   chiqarishda avval ushbu startup xatti-harakati bo‘yicha qaror qabul qiling.
3. Funksiya o‘chiq holda qoladi. Uni keyin yoqish alohida production amali.
   Yoqishga ruxsat berilganda zaxira va tiklash tekshiruvlarini yangilang.
   Tasdiqlangan migratsiya sessiyasida DATABASE_URL ni logga chiqarmasdan
   quyidagi buyruqni bajaring.

       python -B -c "from database.activity import migrate; migrate()"

   U bitta tranzaksiyada faqat yangi jadval va indekslarni yaratadi.
   Sxema versiyasi 4 qoladi. Tranzaksiya xato bersa, shu yerda to‘xtang.
   Katalog yoki mavjud ma’lumotlarni qayta import qilmang.
4. Yangi jadval, indekslar, sxema versiyasi va katalog o‘qishlari
   tasdiqlangach, Render’da bayroqni true qiling. Startup migratsiyasi
   takror ishlashi mumkin. Yangi deployni va sinov akkaunti bilan
   xabarnoma, rozilik, profil, begona callback rad etilishi va qaydni
   o‘chirishni tekshiring.

## Tiklash

Muammo chiqsa funksiyani o‘chiring yoki Render’ni avvalgi sog‘lom deployga
qaytaring. Dashboard orqali rollback Auto-Deploy rejimini o‘chiradi.
Keyingi chiqarishdan oldin uning kutilgan holatini tekshiring.
Migratsiya qo‘shimcha jadvaldan iborat bo‘lgani uchun katalogni tiklash yoki
sxema versiyasini pasaytirish talab qilinmaydi. Funksiya o‘chirilganda bot
orqali tozalash va o‘chirish ham to‘xtaydi. Operator muddatlarni bajarish uchun
tozalashni alohida ishga tushirishi yoki funksiyadan butunlay voz kechilsa,
tegishli tasdiq bilan faqat yangi jadvalni olib tashlashi kerak.
To‘liq tiklash zarur bo‘lsa, avval alohida branch’da tekshiring. Eski
zaxiradagi ixtiyoriy qaydlarni qayta faollashtirmang, chunki ularning
orasida o‘chirish so‘ralgan yozuvlar bo‘lishi mumkin.

[Neon’ning vaqt bo‘yicha tiklash va snapshot hujjati](https://neon.com/blog/announcing-neon-snapshots-a-smoother-path-to-recovery)

[Render rollback hujjati](https://render.com/docs/rollbacks)
