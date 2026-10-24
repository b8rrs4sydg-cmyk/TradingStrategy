"""Asian airport catalog (Taiwan, China, Hong Kong/Macau, Japan, Korea, South-East / South / Central / West Asia).

Scheduled passenger airports with an IATA code. Only identity lives here — code, 中文名, ISO-2 country, IANA time zone,
UI group, and whether it is a main international gateway (candidate 外站 for a 四腿票) — never prices (those come only
from the Google Flights fare database). One line per airport::

    CODE|名稱|COUNTRY|IANA time zone|group|gateway (1 = 外站 candidate)

``app/data/airports.py`` merges this catalog into ``DESTINATIONS`` / ``TW_ORIGINS`` / ``BY_CODE`` / ``TIMEZONES`` and
``scripts/embed_airports.py`` writes the same table into ``public/index.html`` (a test keeps the two in sync).
"""

from __future__ import annotations

GROUPS: tuple[str, ...] = (
    "台灣", "日本", "韓國", "港澳", "中國大陸", "東南亞", "南亞", "中亞/蒙古", "西亞/中東",
)

_TABLE = """
# --- 台灣 (出發機場) ---
TPE|台北桃園|TW|Asia/Taipei|台灣|0
TSA|台北松山|TW|Asia/Taipei|台灣|0
KHH|高雄|TW|Asia/Taipei|台灣|0
RMQ|台中|TW|Asia/Taipei|台灣|0
TNN|台南|TW|Asia/Taipei|台灣|0
CYI|嘉義|TW|Asia/Taipei|台灣|0
HUN|花蓮|TW|Asia/Taipei|台灣|0
TTT|台東|TW|Asia/Taipei|台灣|0
MZG|澎湖馬公|TW|Asia/Taipei|台灣|0
KNH|金門|TW|Asia/Taipei|台灣|0
LZN|馬祖南竿|TW|Asia/Taipei|台灣|0
MFK|馬祖北竿|TW|Asia/Taipei|台灣|0
GNI|綠島|TW|Asia/Taipei|台灣|0
KYD|蘭嶼|TW|Asia/Taipei|台灣|0
WOT|望安|TW|Asia/Taipei|台灣|0
CMJ|七美|TW|Asia/Taipei|台灣|0
PIF|屏東|TW|Asia/Taipei|台灣|0
HCN|恆春|TW|Asia/Taipei|台灣|0
# --- 日本 ---
NRT|東京成田|JP|Asia/Tokyo|日本|1
HND|東京羽田|JP|Asia/Tokyo|日本|1
KIX|大阪關西|JP|Asia/Tokyo|日本|1
ITM|大阪伊丹|JP|Asia/Tokyo|日本|0
UKB|神戶|JP|Asia/Tokyo|日本|0
NGO|名古屋中部|JP|Asia/Tokyo|日本|0
FUK|福岡|JP|Asia/Tokyo|日本|1
KKJ|北九州|JP|Asia/Tokyo|日本|0
CTS|札幌新千歲|JP|Asia/Tokyo|日本|0
OKA|沖繩那霸|JP|Asia/Tokyo|日本|0
ISG|石垣島|JP|Asia/Tokyo|日本|0
MMY|宮古島|JP|Asia/Tokyo|日本|0
UEO|久米島|JP|Asia/Tokyo|日本|0
SDJ|仙台|JP|Asia/Tokyo|日本|0
HIJ|廣島|JP|Asia/Tokyo|日本|0
OKJ|岡山|JP|Asia/Tokyo|日本|0
KOJ|鹿兒島|JP|Asia/Tokyo|日本|0
KMJ|熊本|JP|Asia/Tokyo|日本|0
NGS|長崎|JP|Asia/Tokyo|日本|0
OIT|大分|JP|Asia/Tokyo|日本|0
KMI|宮崎|JP|Asia/Tokyo|日本|0
HSG|佐賀|JP|Asia/Tokyo|日本|0
MYJ|松山|JP|Asia/Tokyo|日本|0
TAK|高松|JP|Asia/Tokyo|日本|0
TKS|德島|JP|Asia/Tokyo|日本|0
KCZ|高知|JP|Asia/Tokyo|日本|0
UBJ|山口宇部|JP|Asia/Tokyo|日本|0
TTJ|鳥取|JP|Asia/Tokyo|日本|0
YGJ|米子|JP|Asia/Tokyo|日本|0
KMQ|小松|JP|Asia/Tokyo|日本|0
TOY|富山|JP|Asia/Tokyo|日本|0
KIJ|新潟|JP|Asia/Tokyo|日本|0
FSZ|靜岡|JP|Asia/Tokyo|日本|0
IBR|茨城|JP|Asia/Tokyo|日本|0
AOJ|青森|JP|Asia/Tokyo|日本|0
AXT|秋田|JP|Asia/Tokyo|日本|0
GAJ|山形|JP|Asia/Tokyo|日本|0
FKS|福島|JP|Asia/Tokyo|日本|0
HKD|函館|JP|Asia/Tokyo|日本|0
AKJ|旭川|JP|Asia/Tokyo|日本|0
KUH|釧路|JP|Asia/Tokyo|日本|0
OBO|帶廣|JP|Asia/Tokyo|日本|0
MMB|女滿別|JP|Asia/Tokyo|日本|0
ASJ|奄美大島|JP|Asia/Tokyo|日本|0
# --- 韓國 ---
ICN|首爾仁川|KR|Asia/Seoul|韓國|1
GMP|首爾金浦|KR|Asia/Seoul|韓國|1
PUS|釜山金海|KR|Asia/Seoul|韓國|0
CJU|濟州|KR|Asia/Seoul|韓國|0
TAE|大邱|KR|Asia/Seoul|韓國|0
CJJ|清州|KR|Asia/Seoul|韓國|0
KWJ|光州|KR|Asia/Seoul|韓國|0
MWX|務安|KR|Asia/Seoul|韓國|0
YNY|襄陽|KR|Asia/Seoul|韓國|0
RSU|麗水|KR|Asia/Seoul|韓國|0
USN|蔚山|KR|Asia/Seoul|韓國|0
HIN|泗川晉州|KR|Asia/Seoul|韓國|0
# --- 港澳 ---
HKG|香港|HK|Asia/Hong_Kong|港澳|1
MFM|澳門|MO|Asia/Macau|港澳|1
# --- 中國大陸 ---
PEK|北京首都|CN|Asia/Shanghai|中國大陸|1
PKX|北京大興|CN|Asia/Shanghai|中國大陸|1
PVG|上海浦東|CN|Asia/Shanghai|中國大陸|1
SHA|上海虹橋|CN|Asia/Shanghai|中國大陸|1
CAN|廣州白雲|CN|Asia/Shanghai|中國大陸|1
SZX|深圳寶安|CN|Asia/Shanghai|中國大陸|1
XMN|廈門高崎|CN|Asia/Shanghai|中國大陸|1
CTU|成都雙流|CN|Asia/Shanghai|中國大陸|1
TFU|成都天府|CN|Asia/Shanghai|中國大陸|0
CKG|重慶江北|CN|Asia/Shanghai|中國大陸|1
XIY|西安咸陽|CN|Asia/Shanghai|中國大陸|1
HGH|杭州蕭山|CN|Asia/Shanghai|中國大陸|1
NKG|南京祿口|CN|Asia/Shanghai|中國大陸|1
WUH|武漢天河|CN|Asia/Shanghai|中國大陸|1
CSX|長沙黃花|CN|Asia/Shanghai|中國大陸|1
TAO|青島膠東|CN|Asia/Shanghai|中國大陸|1
TSN|天津濱海|CN|Asia/Shanghai|中國大陸|1
SHE|瀋陽桃仙|CN|Asia/Shanghai|中國大陸|0
DLC|大連周水子|CN|Asia/Shanghai|中國大陸|0
HRB|哈爾濱太平|CN|Asia/Shanghai|中國大陸|0
CGQ|長春龍嘉|CN|Asia/Shanghai|中國大陸|0
CGO|鄭州新鄭|CN|Asia/Shanghai|中國大陸|0
KMG|昆明長水|CN|Asia/Shanghai|中國大陸|1
FOC|福州長樂|CN|Asia/Shanghai|中國大陸|1
TNA|濟南遙牆|CN|Asia/Shanghai|中國大陸|0
NNG|南寧吳圩|CN|Asia/Shanghai|中國大陸|0
KWE|貴陽龍洞堡|CN|Asia/Shanghai|中國大陸|0
HAK|海口美蘭|CN|Asia/Shanghai|中國大陸|0
SYX|三亞鳳凰|CN|Asia/Shanghai|中國大陸|0
LHW|蘭州中川|CN|Asia/Shanghai|中國大陸|0
INC|銀川河東|CN|Asia/Shanghai|中國大陸|0
TYN|太原武宿|CN|Asia/Shanghai|中國大陸|0
SJW|石家莊正定|CN|Asia/Shanghai|中國大陸|0
HFE|合肥新橋|CN|Asia/Shanghai|中國大陸|0
NGB|寧波櫟社|CN|Asia/Shanghai|中國大陸|0
WNZ|溫州龍灣|CN|Asia/Shanghai|中國大陸|0
ZUH|珠海金灣|CN|Asia/Shanghai|中國大陸|0
HET|呼和浩特白塔|CN|Asia/Shanghai|中國大陸|0
LXA|拉薩貢嘎|CN|Asia/Shanghai|中國大陸|0
XNN|西寧曹家堡|CN|Asia/Shanghai|中國大陸|0
LJG|麗江三義|CN|Asia/Shanghai|中國大陸|0
KWL|桂林兩江|CN|Asia/Shanghai|中國大陸|0
YNT|煙台蓬萊|CN|Asia/Shanghai|中國大陸|0
WUX|無錫碩放|CN|Asia/Shanghai|中國大陸|0
JJN|泉州晉江|CN|Asia/Shanghai|中國大陸|0
KHN|南昌昌北|CN|Asia/Shanghai|中國大陸|0
SWA|揭陽潮汕|CN|Asia/Shanghai|中國大陸|0
DYG|張家界荷花|CN|Asia/Shanghai|中國大陸|0
WEH|威海大水泊|CN|Asia/Shanghai|中國大陸|0
YNJ|延吉朝陽川|CN|Asia/Shanghai|中國大陸|0
TXN|黃山屯溪|CN|Asia/Shanghai|中國大陸|0
URC|烏魯木齊地窩堡|CN|Asia/Urumqi|中國大陸|0
KHG|喀什|CN|Asia/Urumqi|中國大陸|0
# --- 東南亞 ---
BKK|曼谷素萬那普|TH|Asia/Bangkok|東南亞|1
DMK|曼谷廊曼|TH|Asia/Bangkok|東南亞|1
CNX|清邁|TH|Asia/Bangkok|東南亞|0
CEI|清萊|TH|Asia/Bangkok|東南亞|0
HKT|普吉島|TH|Asia/Bangkok|東南亞|1
USM|蘇美島|TH|Asia/Bangkok|東南亞|0
KBV|甲米|TH|Asia/Bangkok|東南亞|0
HDY|合艾|TH|Asia/Bangkok|東南亞|0
UTP|芭達雅烏塔堡|TH|Asia/Bangkok|東南亞|0
KKC|孔敬|TH|Asia/Bangkok|東南亞|0
UBP|烏汶|TH|Asia/Bangkok|東南亞|0
URT|素叻他尼|TH|Asia/Bangkok|東南亞|0
SGN|胡志明市|VN|Asia/Ho_Chi_Minh|東南亞|1
HAN|河內|VN|Asia/Ho_Chi_Minh|東南亞|1
DAD|峴港|VN|Asia/Ho_Chi_Minh|東南亞|1
CXR|芽莊金蘭|VN|Asia/Ho_Chi_Minh|東南亞|0
PQC|富國島|VN|Asia/Ho_Chi_Minh|東南亞|0
HPH|海防|VN|Asia/Ho_Chi_Minh|東南亞|0
HUI|順化|VN|Asia/Ho_Chi_Minh|東南亞|0
DLI|大叻|VN|Asia/Ho_Chi_Minh|東南亞|0
VCA|芹苴|VN|Asia/Ho_Chi_Minh|東南亞|0
VII|榮市|VN|Asia/Ho_Chi_Minh|東南亞|0
MNL|馬尼拉|PH|Asia/Manila|東南亞|1
CEB|宿霧|PH|Asia/Manila|東南亞|1
CRK|克拉克|PH|Asia/Manila|東南亞|1
DVO|納卯|PH|Asia/Manila|東南亞|0
ILO|伊洛伊洛|PH|Asia/Manila|東南亞|0
KLO|卡利博(長灘島)|PH|Asia/Manila|東南亞|0
BCD|巴科洛德|PH|Asia/Manila|東南亞|0
TAG|薄荷島|PH|Asia/Manila|東南亞|0
PPS|巴拉望公主港|PH|Asia/Manila|東南亞|0
USU|科隆|PH|Asia/Manila|東南亞|0
CGY|卡加延德奧羅|PH|Asia/Manila|東南亞|0
ZAM|三寶顏|PH|Asia/Manila|東南亞|0
KUL|吉隆坡|MY|Asia/Kuala_Lumpur|東南亞|1
PEN|檳城|MY|Asia/Kuala_Lumpur|東南亞|1
LGK|蘭卡威|MY|Asia/Kuala_Lumpur|東南亞|0
JHB|新山|MY|Asia/Kuala_Lumpur|東南亞|0
SZB|梳邦|MY|Asia/Kuala_Lumpur|東南亞|0
IPH|怡保|MY|Asia/Kuala_Lumpur|東南亞|0
KBR|哥打峇魯|MY|Asia/Kuala_Lumpur|東南亞|0
KUA|關丹|MY|Asia/Kuala_Lumpur|東南亞|0
BKI|亞庇|MY|Asia/Kuching|東南亞|1
KCH|古晉|MY|Asia/Kuching|東南亞|0
MYY|美里|MY|Asia/Kuching|東南亞|0
TWU|斗湖|MY|Asia/Kuching|東南亞|0
SBW|詩巫|MY|Asia/Kuching|東南亞|0
SIN|新加坡|SG|Asia/Singapore|東南亞|1
CGK|雅加達蘇卡諾哈達|ID|Asia/Jakarta|東南亞|1
HLP|雅加達哈林|ID|Asia/Jakarta|東南亞|0
SUB|泗水|ID|Asia/Jakarta|東南亞|0
JOG|日惹|ID|Asia/Jakarta|東南亞|0
YIA|日惹新機場|ID|Asia/Jakarta|東南亞|0
KNO|棉蘭|ID|Asia/Jakarta|東南亞|0
BDO|萬隆|ID|Asia/Jakarta|東南亞|0
SRG|三寶壟|ID|Asia/Jakarta|東南亞|0
PLM|巨港|ID|Asia/Jakarta|東南亞|0
PDG|巴東|ID|Asia/Jakarta|東南亞|0
BTH|巴淡島|ID|Asia/Jakarta|東南亞|0
PKU|北干巴魯|ID|Asia/Jakarta|東南亞|0
SOC|梭羅|ID|Asia/Jakarta|東南亞|0
BWX|班尤旺吉|ID|Asia/Jakarta|東南亞|0
DPS|峇里島登巴薩|ID|Asia/Makassar|東南亞|1
UPG|望加錫|ID|Asia/Makassar|東南亞|0
BPN|巴厘巴板|ID|Asia/Makassar|東南亞|0
LOP|龍目島|ID|Asia/Makassar|東南亞|0
MDC|萬鴉老|ID|Asia/Makassar|東南亞|0
LBJ|納閩巴霍|ID|Asia/Makassar|東南亞|0
KOE|古邦|ID|Asia/Makassar|東南亞|0
AMQ|安汶|ID|Asia/Jayapura|東南亞|0
DJJ|查亞普拉|ID|Asia/Jayapura|東南亞|0
PNH|金邊|KH|Asia/Phnom_Penh|東南亞|1
REP|暹粒|KH|Asia/Phnom_Penh|東南亞|1
KOS|西哈努克|KH|Asia/Phnom_Penh|東南亞|0
VTE|永珍|LA|Asia/Vientiane|東南亞|0
LPQ|龍坡邦|LA|Asia/Vientiane|東南亞|0
RGN|仰光|MM|Asia/Yangon|東南亞|1
MDL|曼德勒|MM|Asia/Yangon|東南亞|0
NYT|奈比多|MM|Asia/Yangon|東南亞|0
BWN|汶萊斯里巴加灣|BN|Asia/Brunei|東南亞|0
DIL|帝力|TL|Asia/Dili|東南亞|0
# --- 南亞 ---
DEL|新德里|IN|Asia/Kolkata|南亞|1
BOM|孟買|IN|Asia/Kolkata|南亞|1
BLR|班加羅爾|IN|Asia/Kolkata|南亞|1
MAA|清奈|IN|Asia/Kolkata|南亞|1
CCU|加爾各答|IN|Asia/Kolkata|南亞|0
HYD|海得拉巴|IN|Asia/Kolkata|南亞|0
AMD|艾哈邁達巴德|IN|Asia/Kolkata|南亞|0
COK|科欽|IN|Asia/Kolkata|南亞|0
GOX|果阿莫帕|IN|Asia/Kolkata|南亞|0
GOI|果阿達博林|IN|Asia/Kolkata|南亞|0
PNQ|浦那|IN|Asia/Kolkata|南亞|0
JAI|齋浦爾|IN|Asia/Kolkata|南亞|0
LKO|勒克瑙|IN|Asia/Kolkata|南亞|0
TRV|特里凡得琅|IN|Asia/Kolkata|南亞|0
ATQ|阿姆利則|IN|Asia/Kolkata|南亞|0
GAU|古瓦哈提|IN|Asia/Kolkata|南亞|0
IXC|昌迪加爾|IN|Asia/Kolkata|南亞|0
CCJ|卡利卡特|IN|Asia/Kolkata|南亞|0
VNS|瓦拉納西|IN|Asia/Kolkata|南亞|0
PAT|巴特那|IN|Asia/Kolkata|南亞|0
BBI|布巴內斯瓦爾|IN|Asia/Kolkata|南亞|0
NAG|那格浦爾|IN|Asia/Kolkata|南亞|0
IDR|印多爾|IN|Asia/Kolkata|南亞|0
SXR|斯利那加|IN|Asia/Kolkata|南亞|0
IXL|列城|IN|Asia/Kolkata|南亞|0
CJB|哥印拜陀|IN|Asia/Kolkata|南亞|0
VTZ|維沙卡帕特南|IN|Asia/Kolkata|南亞|0
KHI|喀拉蚩|PK|Asia/Karachi|南亞|0
LHE|拉合爾|PK|Asia/Karachi|南亞|0
ISB|伊斯蘭馬巴德|PK|Asia/Karachi|南亞|0
DAC|達卡|BD|Asia/Dhaka|南亞|0
CGP|吉大港|BD|Asia/Dhaka|南亞|0
CMB|可倫坡|LK|Asia/Colombo|南亞|1
KTM|加德滿都|NP|Asia/Kathmandu|南亞|0
PKR|波卡拉|NP|Asia/Kathmandu|南亞|0
PBH|帕羅|BT|Asia/Thimphu|南亞|0
MLE|馬列(馬爾地夫)|MV|Indian/Maldives|南亞|1
KBL|喀布爾|AF|Asia/Kabul|南亞|0
# --- 中亞/蒙古 ---
ULN|烏蘭巴托|MN|Asia/Ulaanbaatar|中亞/蒙古|0
TAS|塔什干|UZ|Asia/Tashkent|中亞/蒙古|0
SKD|撒馬爾罕|UZ|Asia/Tashkent|中亞/蒙古|0
ALA|阿拉木圖|KZ|Asia/Almaty|中亞/蒙古|0
NQZ|阿斯塔納|KZ|Asia/Almaty|中亞/蒙古|0
FRU|比什凱克|KG|Asia/Bishkek|中亞/蒙古|0
DYU|杜尚別|TJ|Asia/Dushanbe|中亞/蒙古|0
ASB|阿什哈巴德|TM|Asia/Ashgabat|中亞/蒙古|0
# --- 西亞/中東 ---
DXB|杜拜|AE|Asia/Dubai|西亞/中東|1
AUH|阿布達比|AE|Asia/Dubai|西亞/中東|0
SHJ|沙迦|AE|Asia/Dubai|西亞/中東|0
DOH|杜哈|QA|Asia/Qatar|西亞/中東|1
RUH|利雅德|SA|Asia/Riyadh|西亞/中東|0
JED|吉達|SA|Asia/Riyadh|西亞/中東|0
DMM|達曼|SA|Asia/Riyadh|西亞/中東|0
MED|麥地那|SA|Asia/Riyadh|西亞/中東|0
KWI|科威特|KW|Asia/Kuwait|西亞/中東|0
BAH|巴林|BH|Asia/Bahrain|西亞/中東|0
MCT|馬斯喀特|OM|Asia/Muscat|西亞/中東|0
TLV|特拉維夫|IL|Asia/Jerusalem|西亞/中東|0
AMM|安曼|JO|Asia/Amman|西亞/中東|0
BEY|貝魯特|LB|Asia/Beirut|西亞/中東|0
IKA|德黑蘭何梅尼|IR|Asia/Tehran|西亞/中東|0
THR|德黑蘭梅赫拉巴德|IR|Asia/Tehran|西亞/中東|0
MHD|馬什哈德|IR|Asia/Tehran|西亞/中東|0
SYZ|設拉子|IR|Asia/Tehran|西亞/中東|0
BGW|巴格達|IQ|Asia/Baghdad|西亞/中東|0
EBL|艾比爾|IQ|Asia/Baghdad|西亞/中東|0
DAM|大馬士革|SY|Asia/Damascus|西亞/中東|0
TBS|提比里斯|GE|Asia/Tbilisi|西亞/中東|0
EVN|埃里溫|AM|Asia/Yerevan|西亞/中東|0
GYD|巴庫|AZ|Asia/Baku|西亞/中東|0
IST|伊斯坦堡|TR|Europe/Istanbul|西亞/中東|1
SAW|伊斯坦堡薩比哈|TR|Europe/Istanbul|西亞/中東|0
AYT|安塔利亞|TR|Europe/Istanbul|西亞/中東|0
ESB|安卡拉|TR|Europe/Istanbul|西亞/中東|0
ADB|伊茲密爾|TR|Europe/Istanbul|西亞/中東|0
"""


def _parse(table: str) -> tuple[tuple[str, str, str, str, str, bool], ...]:
    rows = []
    for line in table.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        code, name, country, tz, group, gateway = line.split("|")
        rows.append((code, name, country, tz, group, gateway == "1"))
    return tuple(rows)


#: (code, 中文名, country, IANA time zone, group, gateway)
ASIA_AIRPORTS: tuple[tuple[str, str, str, str, str, bool], ...] = _parse(_TABLE)
