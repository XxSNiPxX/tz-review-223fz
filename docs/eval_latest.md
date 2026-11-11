Loading weights:   0%|          | 0/57 [00:00<?, ?it/s]Loading weights: 100%|██████████| 57/57 [00:00<00:00, 7787.98it/s]

=== lift_source.docx: 14 findings, kind=WORKS
  [OK ] must L1 CONTRADICTION          Тип лифта: таблица характеристик говорит «пассажирский», предмет закупки и специ  <- CONTRADICTORY_REQUIREMENTS (FLAGGED)
  [OK ] must L2 CONTRADICTION          Грузоподъемность: 300 кг в таблице характеристик против 500 кг в спецификации ра  <- CONTRADICTORY_REQUIREMENTS (FLAGGED)
  [OK ] must L3 CONTRADICTION          Проем двери: 850х2100 в таблице против 850х2000 в спецификации  <- DIMENSION_MISMATCH (INSUFFICIENT_EVIDENCE)
  [OK ] must L4 WARRANTY               Гарантия на работы отсчитывается от товарной накладной; для подряда основание —   <- WARRANTY_BASIS_MISMATCH (FLAGGED)
  [OK ] must L5 STANDARDS              ГОСТ 53782-2010 и ГОСТ 53783-2010 обозначены без «Р»: это национальные стандарты  <- STANDARD_DESIGNATION (INSUFFICIENT_EVIDENCE)
  [OK ] must L6 WRONG_OKPD2            Код ОКПД2 43.29.19.120 не соответствует работам по замене лифта (43.29.19.110);   <- OKPD2_MISSING_GOODS_LINE (FLAGGED)
  [OK ] opt  L7 CONTRADICTION          Спецификация озаглавлена «ремонтные работы», предмет — работы по замене; при нал  <- TITLE_SUBJECT_MISMATCH (FLAGGED)
  [OK ] opt  L8 FORM                   Сроки указаны только цифрами; принято дублировать прописью  <- NUMBER_WITHOUT_WORDS (INSUFFICIENT_EVIDENCE)

=== metrology_source.docx: 21 findings, kind=GOODS
  [OK ] must M1 COMPLETENESS           Позиции-«комплекты» (ручной мерительный инструмент, вспомогательный инструмент,   <- KIT_SHOULD_BE_SPLIT (INSUFFICIENT_EVIDENCE)
  [OK ] must M2 WRONG_OKPD2            Коды ОКПД2 слишком общие (…190) или неверные для позиций: плита поверочная 26.51  <- OKPD2_TOO_GENERIC (INSUFFICIENT_EVIDENCE)
  [OK ] must M3 COMPLETENESS           Не у всех позиций указаны характеристики и комплектность  <- KIT_WITHOUT_COMPOSITION (INSUFFICIENT_EVIDENCE)
  [OK ] opt  M4 COMPLETENESS           Пусконаладочные работы и инструктаж не раскрыты по позициям  <- COMMISSIONING_NOT_PER_ITEM (INSUFFICIENT_EVIDENCE)
  [OK ] must M5 OUT_OF_SCOPE_PROVISION Фраза о применении национального режима не относится к ТЗ и может противоречить   <- NATIONAL_REGIME_STATEMENT (INSUFFICIENT_EVIDENCE)
  [OK ] opt  M6 COMPETITION_RESTRICTION Проверка позиций на соответствие перечню закупок у СМП  <- SME_LIST_CHECK (INSUFFICIENT_EVIDENCE)

=== lift_final.docx: 4 findings, kind=WORKS
  [ok ] INCORRECT_CHARACTERISTIC VAGUE_REQUIREMENT            NOTE  INSUFFICIENT_EVIDENCE Оценочная формулировка (по согласованию с заказчиком) в общих условиях
  [ok ] STANDARDS              INCOMPLETE_STANDARD_REFERENCE NOTE  INSUFFICIENT_EVIDENCE Общая отсылка к действующим ГОСТ/СНиП без конкретных обозначений: допу
  [ok ] INCORRECT_CHARACTERISTIC MISSING_UNIT                 RISK  INSUFFICIENT_EVIDENCE Числовое значение (4) указано без единицы измерения при наличии измери
  [ok ] COMPLETENESS           OPEN_ENUMERATION             NOTE  INSUFFICIENT_EVIDENCE Открытый перечень (и др.) в требованиях к предмету закупки: участник н

=== metrology_final.docx: 15 findings, kind=GOODS
  [ok ] INCORRECT_CHARACTERISTIC MISSING_UNIT                 RISK  INSUFFICIENT_EVIDENCE Числовое значение (4, 25) указано без единицы измерения при наличии из
  [ok ] INCORRECT_CHARACTERISTIC MISSING_UNIT                 RISK  INSUFFICIENT_EVIDENCE Числовое значение (1000) указано без единицы измерения при наличии изм
  [ok ] INCORRECT_CHARACTERISTIC MISSING_UNIT                 RISK  INSUFFICIENT_EVIDENCE Числовое значение (8, 50) указано без единицы измерения при наличии из
  [ok ] COMPLETENESS           OPEN_ENUMERATION             NOTE  INSUFFICIENT_EVIDENCE Открытый перечень (и т.п.) в требованиях к предмету закупки: участник 
  [ok ] STANDARDS              INCOMPLETE_STANDARD_REFERENCE NOTE  INSUFFICIENT_EVIDENCE Стандарт «ГОСТ Р ИСО 4287.» указан без года принятия; проверить актуал
  [ok ] STANDARDS              INCOMPLETE_STANDARD_REFERENCE NOTE  INSUFFICIENT_EVIDENCE Стандарт «ГОСТ 9013.» указан без года принятия; проверить актуальность
  [ok ] STANDARDS              INCOMPLETE_STANDARD_REFERENCE NOTE  INSUFFICIENT_EVIDENCE Стандарт «ГОСТ 10905.» указан без года принятия; проверить актуальност
  [ok ] WRONG_OKPD2            OKPD2_TOO_GENERIC            RISK  INSUFFICIENT_EVIDENCE Код 26.51.66.190 («Инструменты, приборы и машины для измерения или кон
  [ok ] WRONG_OKPD2            OKPD2_TOO_GENERIC            RISK  INSUFFICIENT_EVIDENCE Код 26.51.45.190 («Приборы и аппаратура для измерения или контроля эле
  [ok ] WRONG_OKPD2            OKPD2_TOO_GENERIC            RISK  INSUFFICIENT_EVIDENCE Код 26.51.66.190 («Инструменты, приборы и машины для измерения или кон
  [ok ] WRONG_OKPD2            OKPD2_TOO_GENERIC            RISK  INSUFFICIENT_EVIDENCE Код 26.51.45.190 («Приборы и аппаратура для измерения или контроля эле
  [ok ] WRONG_OKPD2            OKPD2_TOO_GENERIC            RISK  INSUFFICIENT_EVIDENCE Код 26.51.66.190 («Инструменты, приборы и машины для измерения или кон
  [ok ] COMPLETENESS           KIT_WITHOUT_COMPOSITION      ERROR INSUFFICIENT_EVIDENCE Позиция «Набор радиусных шаблонов R7–R25 мм» заявлена как комплект/наб
  [ok ] FORM                   NUMBER_WITHOUT_WORDS         NOTE  INSUFFICIENT_EVIDENCE Срок указан только цифрами; в закупочной документации принято дублиров
  [ok ] COMPETITION_RESTRICTION SME_LIST_CHECK               RISK  INSUFFICIENT_EVIDENCE Закупка упоминает субъектов МСП; 33 кодов ОКПД2 нужно сверить с перечн

=== synthetic_cleaning.docx: 14 findings, kind=SERVICES
  [OK ] must S1 CONTRADICTION          площадь 1200 м² в тексте vs 1500 м² в таблице  <- CONTRADICTORY_REQUIREMENTS (FLAGGED)
  [OK ] must S2 WARRANTY               гарантия на услуги от товарной накладной  <- WARRANTY_BASIS_MISMATCH (FLAGGED)
  [OK ] must S3 WRONG_OKPD2            код работ 43.29.19.110 у поломоечной машины  <- OKPD2_KIND_MISMATCH (FLAGGED)
  [OK ] must S4 STANDARDS              ГОСТ 58393-2019 без Р  <- STANDARD_DESIGNATION (INSUFFICIENT_EVIDENCE)
  [OK ] must S5 COMPETITION_RESTRICTION Grass Floor Wash без «или эквивалент»  <- BRAND_REFERENCE (FLAGGED)
  [OK ] must S6 INCORRECT_CHARACTERISTIC температура воды не менее 40 без единицы  <- MISSING_UNIT (INSUFFICIENT_EVIDENCE)
  [OK ] must S7 INCORRECT_CHARACTERISTIC качественной / современным  <- VAGUE_REQUIREMENT (FLAGGED)
  [OK ] must S8 COMPLETENESS           комплект уборочного инвентаря без состава  <- KIT_WITHOUT_COMPOSITION (FLAGGED)
  [OK ] must S9 OUT_OF_SCOPE_PROVISION фраза о национальном режиме  <- NATIONAL_REGIME_STATEMENT (INSUFFICIENT_EVIDENCE)
  [OK ] opt  S10 COMPETITION_RESTRICTION опыт не менее 10 договоров  <- RESTRICTIVE_QUALIFICATION (INSUFFICIENT_EVIDENCE)
  [OK ] opt  S11 FORM                   12 месяцев без прописи  <- NUMBER_WITHOUT_WORDS (INSUFFICIENT_EVIDENCE)

=== it_hardware_tz.docx: 10 findings, kind=GOODS
  [OK ] must I1 COMPETITION_RESTRICTION Lenovo ThinkPad с запретом эквивалента  <- NO_EQUIVALENT (FLAGGED)
  [OK ] must I2 CONTRADICTION          ОЗУ 16 ГБ в тексте vs 32 в таблице  <- CONTRADICTORY_REQUIREMENTS (FLAGGED)
  [OK ] must I3 INCORRECT_CHARACTERISTIC масса не более 1,5 без единицы  <- MISSING_UNIT (INSUFFICIENT_EVIDENCE)
  [OK ] opt  I4 INCORRECT_CHARACTERISTIC не хуже конкурентов / современный  <- VAGUE_REQUIREMENT (INSUFFICIENT_EVIDENCE)
  [OK ] must I5 STANDARDS              ГОСТ 50948-2001 без Р  <- STANDARD_DESIGNATION (FLAGGED)
  [OK ] must I6 COMPLETENESS           комплект периферии без состава  <- KIT_WITHOUT_COMPOSITION (FLAGGED)
  [OK ] must I7 WRONG_OKPD2            обобщающий код .190 у комплекта  <- OKPD2_TOO_GENERIC (INSUFFICIENT_EVIDENCE)
  [OK ] must I8 WRONG_OKPD2            код товара у услуги настройки  <- OKPD2_KIND_MISMATCH (INSUFFICIENT_EVIDENCE)
  [OK ] must I9 WARRANTY               гарантия на товар от КС-2  <- WARRANTY_BASIS_MISMATCH (FLAGGED)

RECALL must: 27/27   optional: 7/7   FALSE POSITIVES on corrected docs: 0
