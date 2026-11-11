Loading weights:   0%|          | 0/57 [00:00<?, ?it/s]Loading weights: 100%|██████████| 57/57 [00:00<00:00, 8559.19it/s]

=== lift_source.docx: 13 findings, kind=WORKS
  [OK ] must L1 CONTRADICTION          Тип лифта: таблица характеристик говорит «пассажирский», предмет закупки и специ  <- CONTRADICTORY_REQUIREMENTS (FLAGGED)
  [OK ] must L2 CONTRADICTION          Грузоподъемность: 300 кг в таблице характеристик против 500 кг в спецификации ра  <- CONTRADICTORY_REQUIREMENTS (FLAGGED)
  [OK ] must L3 CONTRADICTION          Проем двери: 850х2100 в таблице против 850х2000 в спецификации  <- DIMENSION_MISMATCH (INSUFFICIENT_EVIDENCE)
  [OK ] must L4 WARRANTY               Гарантия на работы отсчитывается от товарной накладной; для подряда основание —   <- WARRANTY_BASIS_MISMATCH (FLAGGED)
  [OK ] must L5 STANDARDS              ГОСТ 53782-2010 и ГОСТ 53783-2010 обозначены без «Р»: это национальные стандарты  <- STANDARD_DESIGNATION (INSUFFICIENT_EVIDENCE)
  [OK ] must L6 WRONG_OKPD2            Код ОКПД2 43.29.19.120 не соответствует работам по замене лифта (43.29.19.110);   <- OKPD2_MISSING_GOODS_LINE (FLAGGED)
  [OK ] opt  L7 CONTRADICTION          Спецификация озаглавлена «ремонтные работы», предмет — работы по замене; при нал  <- TITLE_SUBJECT_MISMATCH (FLAGGED)
  [OK ] opt  L8 FORM                   Сроки указаны только цифрами; принято дублировать прописью  <- NUMBER_WITHOUT_WORDS (INSUFFICIENT_EVIDENCE)

=== metrology_source.docx: 19 findings, kind=GOODS
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
  [ok ] INCORRECT_CHARACTERISTIC MISSING_UNIT                 RISK  INSUFFICIENT_EVIDENCE Числовое значение (60) указано без единицы измерения при наличии измер
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
  [ok ] FORM                   NUMBER_WITHOUT_WORDS         NOTE  INSUFFICIENT_EVIDENCE Срок указан только цифрами; в закупочной документации принято дублиров
  [ok ] COMPETITION_RESTRICTION SME_LIST_CHECK               RISK  INSUFFICIENT_EVIDENCE Закупка упоминает субъектов МСП; 33 кодов ОКПД2 нужно сверить с перечн

RECALL must: 10/10   optional: 4/4   FALSE POSITIVES on corrected docs: 0
