# Noticias.lat en vivo

Directos de YouTube armados con las noticias que ya produce [TTS-FMPEG](https://github.com/n14-py/TTS-FMPEG-lfaf) a partir de [lfaftechapi](https://github.com/n14-py/lfaftechapi).

TTS-FMPEG fabrica cada nota (voz, presentador, música) y la publica como video. Este servicio no vuelve a hacer esa nota. Recibe de 8 a 15 videos de los últimos días de un país, los ordena como un noticiero y abre un **directo**.

## Cómo sale al aire

1. lfaftechapi manda un JSON con las notas de Paraguay, Chile, Argentina, México o el país que toque. El formato está en `docs/contrato-lfaftechapi.md` y hay un ejemplo en `examples/payload_paraguay.json`.
2. Se agrupan los primeros 3 de política, después economía, después deportes y el resto. Si un rubro trae más de 3, lo que sobra vuelve más tarde.
3. Gemini escribe el título, la descripción, el saludo y las frases de pase. Si no hay clave de Gemini, entran plantillas distintas en cada emisión.
4. La única voz nueva es la del presentador:
   - intro: bienvenida, nombre del canal, fecha de ese país y con qué bloque arranca;
   - entre bloques: "ahora pasamos a economía" (o "seguimos con más de política" si es el mismo tema);
   - despedida.
5. Esa voz se monta sobre el video que está en `assets_video/templates/` (intros, hombre, mujer). El video se puede cambiar por otro; el motor solo genera la voz, la música baja y un efecto.
6. Cada nota se reproduce completa, tal como la dejó TTS-FMPEG.
7. Se crea el directo en YouTube, público, con grabación y DVR. Se activa la pauta automática cada 10 minutos y un corte de anuncio en cada cambio de bloque.

## Por qué dos vivos no salen iguales

En cada emisión cambia, al azar:

- la voz (hombre o mujer) y la velocidad;
- el nombre con el que se presenta;
- el video de intro y el video del presentador en cada pase;
- la música y el efecto;
- el texto del saludo, de los pases y del título.

El orden de los bloques no se mezcla al azar: política abre, economía sigue. Eso es lo que tiene que sonar a noticiero. Lo que no se repite es la locución y la imagen del pase.

## Arranque

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python generar_token.py
python app.py
```

El puerto por defecto es `3002`.

Docker, igual que el worker de videos:

```bash
docker build -t noticias-lat-en-vivo .
docker run --env-file .env -p 3002:3002 noticias-lat-en-vivo
```

## YouTube y monetización

Los `token_*.json` de TTS-FMPEG solo tienen permiso de subida. Para un vivo hay que autorizar de nuevo con `generar_token.py`. Hace falta, en Google Cloud, la YouTube Data API v3, y en el canal:

- emisiones en directo habilitadas;
- canal en el Programa de Partners si se quieren anuncios;
- monetización de directos activada en YouTube Studio.

El directo pide latencia normal (la latencia ultrabaja no deja mid-rolls), `recordFromStart`, arranque automático y `monetizationDetails.cuepointSchedule`. Además inserta un cuepoint de anuncio en cada cambio de bloque, con una separación mínima de 2 minutos.

Si el canal todavía no puede monetizar, YouTube rechaza la pauta y el vivo sale igual. El log lo dice, y `monetizationEnabled` vuelve en el webhook.

No subas `token_*.json` ni `client_secret_*.json` al repositorio. Van en el servidor, al lado de `app.py`.

## Videos del presentador

Ya están copiados los de TTS-FMPEG:

- `assets_video/templates/intros/` — apertura
- `assets_video/templates/hombre/` y `mujer/` — el periodista, según la voz elegida
- `assets_video/templates/outros/` — si está vacío, se usa `outro_final.png`
- `assets_video/bgm/` y `assets_video/sfx/` — cama y efectos, bajitos, detrás de la voz

Para reemplazarlos, soltá otro mp4 en la misma carpeta. No hace falta tocar código.

## Endpoints

| Método | Ruta | Qué hace |
| --- | --- | --- |
| GET | `/health` | FFmpeg, carpetas de video y estado del vivo |
| POST | `/live/preview` | Título, descripción y escaleta, sin abrir YouTube |
| POST | `/live/start` | Arma el directo y lo transmite |
| GET | `/live/status` | Si está preparando, en vivo o terminó |
| POST | `/live/stop` | Corta la transmisión |

Todos los POST llevan el header `x-api-key`.

## Pruebas

```bash
python -m unittest discover -s tests -v
```
