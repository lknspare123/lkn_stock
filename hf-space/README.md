---
title: LKN Stock Background Remover
emoji: ✂️
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
pinned: false
---

Background remover (rembg) for the LKN Stock web app. `POST /remove` with the picture in the form field `image`
and the header `X-API-Token`. Needs the secret `API_TOKEN`.
