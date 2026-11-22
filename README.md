# Imoti Aggregator (Област Шумен и Област Варна)

Локален Python агрегатор за обяви за недвижими имоти, който събира обяви от множество портали и агенции, нормализира данните, **слива дублирани обяви (между различни сайтове и между множество агенции)** и записва резултата директно в JSON файл без нужда от база данни.

## Включени източници
- `alo.bg` (област Шумен `region_id=26`, област Варна `region_id=3`)
- `imot.bg` (`oblast-shumen`, `oblast-varna`)
- `imoti.net` (`shumen`, `varna`)
- `scrapers/agency_template.py` — готов шаблон за добавяне на сайтове/XML фийдове на агенции

## Как работи сливането на дубликати (`dedup/matcher.py`)
Всеки уникален имот се обединява в един обект `CanonicalProperty`, който съдържа:
- `price_eur_min` / `price_eur_max` (ако различни агенции са обявили различна цена)
- `offers_count` — брой засечени обяви за същия имот
- `sources` — списък от сайтовете, където е намерен
- `agencies` — списък от агенциите, които го предлагат
- `external_links` — всички външни линкове с цена, агенция и сайт
- `merge_reasons` — защо обявите са обединени (локация, квадратура, цена, етаж, телефон, текстово сходство)

## Стартиране
```powershell
cd C:\Users\adm\.gemini\antigravity\scratch\imoti-aggregator
.\.venv\Scripts\python.exe main.py --regions shumen varna --transactions sale --pages 2
```

Резултатите се записват в:
- `data/listings.json` — обединени имоти с външни линкове
- `data/raw_listings.json` — сурови обяви преди сливане
