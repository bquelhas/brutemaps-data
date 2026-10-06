# GTFS não oficiais

Feeds GTFS feitos por nós onde o operador não publica um. Servidos pelo GitHub Pages:

| Feed | Ficheiro | Validade |
|---|---|---|
| Metrobus do Metro Mondego (Coimbra – Lousã – Serpins) | https://bquelhas.github.io/brutemaps-data/gtfs/metro-mondego/metro-mondego.zip | 10 set 2026 – 31 mar 2027 |
| metroBus do Porto (M1 Casa da Música – Império) | https://bquelhas.github.io/brutemaps-data/gtfs/metrobus-porto/metrobus-porto.zip | 20 abr 2026 – 31 mar 2027 |

**Não são oficiais.** Se o operador publicar um GTFS, use esse. Erros: abrir uma issue neste repositório.

## Fontes
- **Metro Mondego:** horários oficiais em PDF (metromondego.pt › Viajar › Horários, "Desde 10 de setembro
  2026"). Suburbanas (S1, S2) com a hora de cada viagem em cada paragem; urbanas (U1, U2, U3) por
  frequências (o PDF só dá 1.ª/última viagem e intervalos), com os tempos entre paragens das suburbanas.
- **metroBus do Porto:** regras oficiais de horário e frequência (metrobus.metrodoporto.pt): todos os dias
  06:30–22:00; dias úteis 10 min nas pontas (07:30–10:00, 16:30–19:30) e 15 min no resto; fins de semana e
  feriados 15 min; 12 min de ponta a ponta, repartidos pela distância.
- **Paragens e traçados:** relações do OpenStreetMap (network=Metro Mondego; M1 operador STCP).

## Licença
Os traçados e as paragens vêm do OpenStreetMap: estes feeds são distribuídos sob a
[Open Database License (ODbL)](https://opendatacommons.org/licenses/odbl/), © contribuidores do OpenStreetMap.
Horários: Metro Mondego e Metro do Porto (informação pública ao passageiro). Se algum operador pedir, o feed sai.

## Validação
Validador da MobilityData 8.0.1: Metro Mondego sem avisos; metroBus do Porto com 1 aviso
(`stops_match_shape_out_of_order` nas pontas: o traçado do OSM dá a volta às rotundas de Casa da Música e Império).

## Atualizar
Os feeds expiram a 31 mar 2027 de propósito (melhor nada do que horários errados). Quando os horários mudam:
- Metro Mondego: o site bloqueia pedidos fora de um browser; extrair o texto dos PDFs (com a posição de cada
  célula) para `metro-mondego/fonte/horarios-<data>.json`, mudar `SRC`/`START`/`END` em `build.py` e correr.
- `python build.py --fresh` volta a ler o OSM.
