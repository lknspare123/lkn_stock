# Free background removal on your own PC - fast version

No domain, no monthly credits, no Cloudinary. The website on Render keeps saving plain pictures; you run ONE command on your PC
and it cleans the pictures and saves them to the same R2 bucket and Neon database. The app then shows the clean versions.

## 1. Apply this update (once)
1. Extract the zip over your project folder (say yes to replace files).
2. Delete the two old Cloudinary scripts if they are still there:
   `scripts\generate_backgrounds.py` and `scripts\relink_cloudinary_images.py`
3. Check that your project has a `.env` file (copy `.env.example` to `.env` if not) with at least:
   `DATABASE_URL`, `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`, `R2_PUBLIC_URL`
   (`R2_PUBLIC_URL` can stay the `https://pub-xxxx.r2.dev` address - this method does not need your own domain.)
4. Push to GitHub so Render gets the new code:
   `git add .`  ->  `git commit -m "fast free background removal"`  ->  `git push`
5. On Render, leave `BG_REMOVER` EMPTY (free Render has too little RAM for rembg).

## 2. First run (test on 5 pictures)
Open PowerShell in the project folder:
```
.\scripts\clean_pictures.ps1 -Limit 5
```
The first time it installs rembg and downloads the model (small for the default `u2netp`). Type `YES` when asked.
Then open those 5 items in the app and look at them.

If PowerShell says scripts are disabled, run this once and try again:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

## 3. Clean everything
```
.\scripts\clean_pictures.ps1
```
You can stop with Ctrl+C and run it again later - it continues with the pictures that are not done.
Failed pictures are written to `images_failed.txt`; run the same command again to retry only those.

## Speed and quality
| What | How | Effect |
|---|---|---|
| Fastest (default) | `-Model u2netp` | quickest, slightly rougher edges |
| Better edges | `-Model u2net` | about 3x slower |
| Best edges | `-Model isnet-general-use` | slowest, needs 1 GB+ RAM |
| Even faster | `-Size 512` | smaller picture for the model |
| CPU use | `$env:REMBG_THREADS = '6'` before the command | default is your number of CPU cores |

Tip: try 5 pictures with `u2netp`. If the edges are good enough for you, keep it. If not, try `-Model u2net -Limit 5`.
To redo pictures that were already cleaned with another model, add `-Force`.

## If you later want it automatic on the website
That needs the Cloudflare option (`BG_REMOVER=cloudflare`, a domain of your own on Cloudflare) - see README step 2b. Nothing in this update removes it.
