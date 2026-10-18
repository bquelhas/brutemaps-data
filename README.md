# brutemaps-data

Linhas de metro e comboio suburbano (OpenStreetMap, ODbL) por quadrícula de 0,2°, para a brute maps. Atualizado todas as semanas pelo GitHub Actions (`build_cells.py`, cidades em `cities.txt`). Servido em https://bquelhas.github.io/brutemaps-data/cells/<lat>_<lon>.json.

Dados © OpenStreetMap contributors, ODbL.

## Painéis de paragens (`boards/`)
`build_boards.py` (todos os dias, GitHub Actions) converte GTFS oficiais que o Transitous ainda não tem em
ficheiros pequenos que a brute maps lê ao tocar numa paragem: `boards/index.json` (redes e retângulos),
`boards/<rede>/meta.json` (linhas, destinos, serviços ativos por dia), `t/<x>_<y>.json` (paragens e
partidas por quadrícula de 0,02°) e `s/<linha>_<sentido>.txt` (traçado, polyline precisão 5).

Fontes: Minho Access Point (CIM do Cávado, Guimabus, Barcelos, V. N. de Famalicão — **CC-BY 4.0**),
Busway (SIT Região de Coimbra, CIRA Região de Aveiro), CIM do Tâmega e Sousa, SMTUC (dados.gov.pt).
Os dados são dos operadores; aqui só mudam de formato.

### Zonas tarifárias (`boards/zones/`)
`build_zones.py`: zonas Andante (Porto) desenhadas a partir da zona de cada paragem do metro e da STCP
(OTP da Porto Digital, CC0): células de Voronoi cortadas a 1,2 km, juntas por zona. **Aproximadas** —
a fronteira oficial é entre paragens, não uma linha no terreno.
