# Dastlabki g'oya (readme.md dan)

> men trading Alert bot yasamoqchi man, buni qanday amalga oshirish bo'yicha maslahat ber,
> kodni kiyinroq yozamiz.
>
> men har kuni tradingview.com yoki exness web tradingview orqali Zona aniqlayman, va python
> script usha zonaga narx usha chizilgan zonalarning birontasiga yaqinlashib kelyotganida
> Alert berishi kerak. masalan ZOnalarni men aniqlab chizdim va script kun 24 soat ishlab
> narx yaqinlashishi bilan, "telethon" lib orqali mening boshqa bir accountimga telegram
> orqali telefon qilib, gapirishi kerak "Tilla narxi 4433 narxga yaqinlashdi. yoki 5 punkt
> uzoqlikda turubdi" deb.

## Qanday bajarildi

| Talab | Bajarilishi |
|---|---|
| Zonalarni men aniqlab kiritaman | `/addzone 4291 4296` — Telegram orqali |
| 24 soat ishlashi | `MonitorLoop` + MT5/Telegram reconnect |
| Narx yaqinlashganda | 60 pips bufer (`BUFFER_PIPS`) |
| Telethon orqali telefon qilish | `tg/calls.py` — raw MTProto `phone.RequestCall` |
| "Tilla narxi ... ga yaqinlashdi" deb gapirishi | `tg/tts.py` — edge-tts voice message (qo'ng'iroq ichida emas, sababi README 4-bo'limda) |
