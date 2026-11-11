#!/usr/bin/env bash
# Build certs/ru_bundle.pem = certifi CA bundle + Russian Trusted Root/Sub CA (Минцифры), which zakupki.gov.ru uses.
# Source: the official gosuslugi download page (https://www.gosuslugi.ru/crt). Verification stays enabled.
set -e
cd "$(dirname "$0")"
mkdir -p certs
curl -fsS -m 30 -o certs/russian_trusted_root_ca.pem https://gu-st.ru/content/lending/russian_trusted_root_ca_pem.crt
curl -fsS -m 30 -o certs/russian_trusted_sub_ca.pem  https://gu-st.ru/content/lending/russian_trusted_sub_ca_pem.crt
CERTIFI=$(python3 -c 'import certifi; print(certifi.where())')
cat "$CERTIFI" certs/russian_trusted_root_ca.pem certs/russian_trusted_sub_ca.pem > certs/ru_bundle.pem
echo "root CA:"; openssl x509 -in certs/russian_trusted_root_ca.pem -noout -subject -enddate -fingerprint -sha256
echo "test:"
curl -s -m 20 --cacert certs/ru_bundle.pem -A "Mozilla/5.0 (X11; Linux x86_64) Chrome/124.0 Safari/537.36" \
  -o /tmp/eis_test.html -w "zakupki with RU bundle: http=%{http_code} bytes=%{size_download}\n" \
  "https://zakupki.gov.ru/epz/order/extendedsearch/results.html?fz223=on&searchString=%D0%BD%D0%BE%D1%83%D1%82%D0%B1%D1%83%D0%BA&pageNumber=1&recordsPerPage=_20"
grep -o "regNumber=3[0-9]*" /tmp/eis_test.html | sort -u | head -3
