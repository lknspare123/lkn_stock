# Free background remover on Hugging Face (works from the phone, no domain)

How it works: the app on Render sends each new picture to a small free "Space" at Hugging Face that runs `rembg`.
The Space sends back the product with a transparent background, the app makes it white / square and stores it on R2.
Everything happens when the picture is saved, so it also works when you upload from the phone.

Good to know
* The free Space can go to sleep when nobody uses it. The first picture after a long pause may need 1-2 minutes
  (the app waits up to 150 s). If that is too long it saves the plain picture and shows a message; the next try works,
  or press the "✨ remove background" button on the item.
* The Space is Public, but only requests that carry your secret token are processed.
* Each picture takes a few seconds on the free CPU.

## A. Create the Space (once, about 10 minutes)
1. Make a free account at https://huggingface.co and log in.
2. Click your picture (top right) -> **New Space**.
   - Space name: `lknstock-bg`
   - SDK: **Docker** -> template **Blank**
   - Hardware: **CPU basic (free)**
   - Visibility: **Public**
   - Click **Create Space**.
3. In the new Space open the **Files** tab -> **Add file** -> **Upload files**, and upload the 4 files from the `hf-space` folder of this zip:
   `Dockerfile`, `app.py`, `requirements.txt`, `README.md`. Click **Commit changes**.
4. Open **Settings** -> **Variables and secrets** -> **New secret**:
   - Name: `API_TOKEN`
   - Value: a long random text. In PowerShell you can make one with:
     `-join ((48..57)+(65..90)+(97..122) | Get-Random -Count 40 | % {[char]$_})`
   - Keep a copy - Render needs the same text.
5. The Space now builds (first build takes several minutes; the Logs tab shows progress). Wait until it says **Running**.
   (If you added the secret after the first build, open **Settings** -> **Factory rebuild** or **Restart**.)
6. Find the Space address: on the Space page click the **⋮** menu -> **Embed this Space** -> copy the **Direct URL**.
   It looks like `https://yourname-lknstock-bg.hf.space`. (If the menu wording is different, it is always
   `https://<your-username>-<space-name>.hf.space`, in lower case.)
7. Test it: open `https://yourname-lknstock-bg.hf.space/health` in the browser. You should see `"ok":true` and `"token_set":true`.

## B. Connect the app
1. Extract this update zip over your project folder (replace files) and delete the two old scripts if still there:
   `scripts\generate_backgrounds.py`, `scripts\relink_cloudinary_images.py`.
2. Add to your local `.env` (for the PC scripts):
   ```
   BG_REMOVER=hf
   HF_SPACE_URL=https://yourname-lknstock-bg.hf.space
   HF_API_TOKEN=the-secret-from-step-A4
   ```
3. Test on one photo (PowerShell, project folder):
   `python scripts/test_images.py "D:\photos\brake_pad.jpg"`
   Open `image_test\after.png` - the product should be on pure white. The first call may take a minute if the Space was asleep.
4. `git add .` -> `git commit -m "Hugging Face background remover"` -> `git push`
5. On Render -> your service -> **Environment** add:
   | Key | Value |
   |---|---|
   | `BG_REMOVER` | `hf` |
   | `HF_SPACE_URL` | `https://yourname-lknstock-bg.hf.space` (no `/` at the end) |
   | `HF_API_TOKEN` | the same secret as in the Space |
   Save - Render redeploys. Do NOT set `REMBG_*` variables on Render.
6. Upload a picture from your phone with the "remove background" option ticked. If the Space was asleep and it took too long,
   you will see "Background removal skipped": wait a minute and press ✨ on the item.

## C. Clean the pictures you already have
```
.\scripts\clean_pictures.ps1 -Limit 5     # test on 5, look at them in the app
.\scripts\clean_pictures.ps1              # then everything
```
It uses your Space automatically (because HF_SPACE_URL is in `.env`). You can stop and run it again; finished pictures are skipped.
To use rembg on this PC instead: `.\scripts\clean_pictures.ps1 -Engine rembg`.

## If it does not work
| Message | Cause |
|---|---|
| `refused the token (401)` | `HF_API_TOKEN` on Render is not exactly the same text as the `API_TOKEN` secret in the Space |
| `HTTP 404 from the Space` | wrong `HF_SPACE_URL`, or the Space is Private (make it Public) |
| `waking up or starting` / `gave up after 150s` | the Space was asleep or still building; open `/health` in the browser, wait for `"ok":true`, try again |
| `no API_TOKEN secret yet` | add the secret in the Space, then Restart it |
| `model is not loaded: ...` | look at the Space **Logs** tab; usually the build is not finished |
| Hugging Face says the Space is paused / out of quota | restart it from the Space page, or tell me and we can use another engine |
