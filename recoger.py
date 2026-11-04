# Consulta una vez la ocupacion de hoy y actualiza datos.json y datos.js.
# Lo ejecuta GitHub Actions cada 30 minutos. Si el servidor avisa de un bloqueo,
# respeta la espera y no vuelve a conectarse hasta que termine.

import http.cookiejar
import json
import re
import sys
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

CARPETA = Path(__file__).resolve().parent
RUTA_JSON = CARPETA / 'datos.json'
RUTA_JS = CARPETA / 'datos.js'
RUTA_PAUSA = CARPETA / 'pausa.txt'
BASE = 'https://reserves.santllorenc.es:12443/deportes'
ZONA = ZoneInfo('Europe/Madrid')


def arreglar_nombre(texto):
    # La respuesta mezcla codificaciones: se lee en Latin-1 y cada nombre se recompone en UTF-8 si es valido.
    try:
        return texto.encode('latin-1').decode('utf-8')
    except UnicodeError:
        return texto


def consultar(ahora):
    # La consulta exige la sesion que se abre al visitar la pagina.
    abridor = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    abridor.addheaders = [('User-Agent', 'Mozilla/5.0 (compatible; PistasSantLlorenc)')]
    abridor.open(f'{BASE}/alqinst.php', timeout=30).read()
    cuerpo = (f"act=todos&comp=todos&dia={ahora:%d/%m/%Y}&tipo=0&numaut=&apli=&tipinst=&dia2="
              "&d1=1&d2=1&d3=1&d4=1&d5=1&d6=1&d7=1&instalacion=todos&nocache=1")
    with abridor.open(f'{BASE}/generainstalaciones.php', data=cuerpo.encode(), timeout=30) as respuesta:
        return respuesta.read().decode('latin-1')


def leer_pistas(html):
    # Cada pista es un bloque "row minihr" con 48 franjas de 30 minutos.
    pistas = {}
    for bloque in html.split('class="row minihr"')[1:]:
        nombre = re.search(r'miniback col-xs-9[^>]*>\s*([^<]+?)\s*<', bloque)
        complejo = re.search(r'text-primary">\s*([^<]+?)\s*<', bloque)
        if not nombre:
            continue
        estados = ''
        for clase in re.findall(r'<div\b([^>]*\btalq\b[^>]*)>\s*\d\d:\d\d\s*</div>', bloque):
            estados += 'R' if 'fondoRojo' in clase else 'V' if 'fondoVerde' in clase else '?'
        if len(estados) == 48:
            clave = nombre.group(1) + '|' + (complejo.group(1) if complejo else '')
            pistas[arreglar_nombre(clave)] = estados
    return pistas


def main():
    ahora = datetime.now(ZONA).replace(tzinfo=None, microsecond=0)

    if RUTA_PAUSA.exists():
        hasta = datetime.fromisoformat(RUTA_PAUSA.read_text().strip())
        if ahora < hasta:
            print(f'En pausa hasta {hasta}; no se consulta.')
            return 0
        RUTA_PAUSA.unlink()

    html = consultar(ahora)

    aviso = re.search(r'Ataque detectado, espere (\d+) segundos', html)
    if aviso:
        hasta = ahora + timedelta(seconds=int(aviso.group(1)) + 60)
        RUTA_PAUSA.write_text(hasta.isoformat())
        print(f'Bloqueado por el servidor; en pausa hasta {hasta}.')
        return 0

    pistas = leer_pistas(html)
    if not pistas:
        print('Respuesta sin pistas:', html[:120])
        return 1

    datos = json.loads(RUTA_JSON.read_text(encoding='utf-8'))
    hoy = datos['dias'].setdefault(f'{ahora:%Y-%m-%d}', {})

    # Las franjas ya pasadas salen ocultas ('?'): se conserva lo ultimo que se vio de ellas.
    for pista, estados in pistas.items():
        previo = hoy.get(pista, '?' * 48)
        hoy[pista] = ''.join(p if e == '?' else e for e, p in zip(estados, previo))

    datos['actualizado'] = ahora.isoformat()
    texto = json.dumps(datos, ensure_ascii=False, indent=2)
    RUTA_JSON.write_text(texto, encoding='utf-8')
    RUTA_JS.write_text(f'window.DATOS = {texto};', encoding='utf-8')
    print(f'Correcto: {len(pistas)} pistas.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
