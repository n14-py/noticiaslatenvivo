# Contrato para lfaftechapi

Este servicio ya recibe el directo. En lfaftechapi, más adelante, solo falta agrupar las notas recientes de un país y hacer un POST. No hay que volver a renderizar cada noticia: se reutiliza el `videoUrl` que ya subió TTS-FMPEG.

## Cuándo dispararlo

Cuando haya entre 8 y 15 notas de los últimos días del mismo país, con `videoProcessingStatus: complete` y `videoUrl` (o el mp4 de R2). Un país por vez.

## POST

`POST {URL_DE_ESTE_SERVICIO}/live/start`

Header: `x-api-key: {ADMIN_API_KEY}` (la misma clave de siempre)

El servidor responde 202 enseguida. El vivo sigue en segundo plano. Un solo directo a la vez: si responde 503, reintentar después.

### Lista plana

El motor agrupa solo: los primeros 3 de política, después economía, después el resto. Si sobran notas de un rubro, vuelven más adelante con otra frase del presentador.

```json
{
  "live_id": "py-2026-09-30-mediodia",
  "pais": "py",
  "canal": "Noticias LAT",
  "videos": [
    {
      "article_id": "66f1a1",
      "titulo": "El Congreso retoma el debate del presupuesto",
      "categoria": "politica",
      "video_url": "https://cdn.ejemplo/politica-1.mp4"
    }
  ]
}
```

`video_url` también acepta `videoUrl` o `url`. `categoria` acepta `category`.

### Bloques ya armados

Si lfaftechapi prefiere mandar los grupos, se respeta ese orden y entre cada grupo entra el presentador.

```json
{
  "pais": "cl",
  "bloques": [
    {
      "categoria": "politica",
      "videos": [{ "titulo": "...", "video_url": "https://...", "article_id": "1" }]
    },
    {
      "categoria": "economia",
      "videos": [{ "titulo": "...", "video_url": "https://...", "article_id": "2" }]
    }
  ]
}
```

## Qué genera este servicio

- Título, descripción y tags del vivo (Gemini si hay clave; si no, plantillas que cambian en cada emisión).
- Voz de la intro: bienvenida, canal, fecha del país y con qué bloque arranca.
- Voz de cada cambio: "ahora pasamos a economía", o "seguimos con más de política" si el bloque es continuación.
- Voz de la despedida.
- Esa voz se mezcla sobre un video de `assets_video/templates/` (intro, hombre o mujer). El video lo podés reemplazar; la locución la hace este motor.
- Las notas se reproducen enteras, como ya salieron de TTS-FMPEG.
- Se crea el directo de YouTube en público, con DVR, grabación desde el inicio y pauta (mid-rolls al cambiar de bloque y cada 10 minutos).

## Avisos de vuelta

Cuando el vivo sale al aire:

`POST {MAIN_API_URL}/api/lives/live_started`

Cuando termina:

`POST {MAIN_API_URL}/api/lives/live_complete`

Si falla:

`POST {MAIN_API_URL}/api/lives/live_failed`

Header `x-api-key`. Cuerpo:

```json
{
  "liveId": "py-2026-09-30-mediodia",
  "pais": "py",
  "paisNombre": "Paraguay",
  "youtubeId": "xxxxxxxxxxx",
  "watchUrl": "https://www.youtube.com/watch?v=xxxxxxxxxxx",
  "title": "EN VIVO: 10 noticias de Paraguay | 30 de septiembre",
  "monetizationEnabled": true,
  "videoCount": 10,
  "voice": "mujer_1",
  "presenter": "Camila",
  "scriptSource": "gemini",
  "status": "live",
  "articleIds": ["66f1a1"]
}
```

Esas tres rutas todavía no existen en lfaftechapi. Si no responden, el directo no se corta: solo queda el aviso en el log.

## Vista previa, sin abrir YouTube

`POST /live/preview` con el mismo JSON. Devuelve título, descripción, intro, puentes y el orden de los bloques.

`GET /live/status` muestra si está preparando, en vivo o terminó.

`POST /live/stop` corta la transmisión.
