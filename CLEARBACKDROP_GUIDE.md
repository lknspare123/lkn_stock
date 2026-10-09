# Free background remover with ClearBackdrop (works from the phone, no domain, no PC needed)

How it works: when a picture is saved in the app (from the phone or the PC), the app sends it to the ClearBackdrop API,
gets the product back on a transparent background, makes it white and square, and stores it on R2.
Free key: 80 pictures a day, 40 an hour. If the limit is reached, the app saves the plain picture and shows a message.
Your product photos are sent to ClearBackdrop's server. A free tier can change later.

## 1. Get the free key
1. Open https://clearbackdrop.com/signup?next=/account and sign up (Google or email).
2. Your API key is on the account page. Copy it.
3. Optional test in PowerShell (use `curl.exe`, not `curl`):
   `curl.exe -X POST -H "X-API-Key: YOUR_KEY" -F "image=@D:\photos\x.jpg" https://clearbackdrop.com/api/v1/remove-background -o result.png`
   Open `result.png` - the product should be on a transparent background. Check the edges on 3 of your photos.

## 2. Apply the update
1. Extract this zip over your project folder (replace files). Delete the two old scripts if still there:
   `scripts\generate_backgrounds.py` and `scripts\relink_cloudinary_images.py`.
2. Add to your local `.env`:
   ```
   BG_REMOVER=clearbackdrop
   CLEARBACKDROP_API_KEY=your-key
   ```
3. Test one photo on your PC:
   `python scripts/test_images.py "D:\photos\x.jpg"`  ->  open `image_test\after.png` (product on pure white).
4. Push: `git add .` -> `git commit -m "ClearBackdrop background remover"` -> `git push`
5. Render -> your service -> Environment -> add:
   | Key | Value |
   |---|---|
   | `BG_REMOVER` | `clearbackdrop` |
   | `CLEARBACKDROP_API_KEY` | your key |
   Save (Render redeploys). Do not add `REMBG_*` variables on Render.
6. On your phone: add or edit an item, choose a photo, tick the remove-background option, save.

## 3. Clean the pictures you already have (the free limit is 40 an hour, 80 a day)
```
.\scripts\clean_pictures.ps1 -Limit 5      # test on 5 and look at them in the app
.\scripts\clean_pictures.ps1 -Limit 40     # one hour's worth
.\scripts\clean_pictures.ps1               # everything; it stops by itself when the limit is reached
```
When the limit is reached the script stops and tells you. Wait (an hour or until tomorrow) and run the SAME command again:
it skips finished pictures and continues with the rest. Failed pictures are listed in `images_failed.txt`.

## If something goes wrong
| Message | Cause |
|---|---|
| `CLEARBACKDROP_API_KEY is not set` | the variable is missing on Render (or in `.env` on your PC) |
| `refused the key (HTTP 401/403)` | wrong or revoked key - copy it again from the account page |
| `free ClearBackdrop limit is used up` | 40 an hour / 80 a day reached - the plain picture was saved; press ✨ on the item later |
| `answered HTTP 500 ... gave up` | their server was busy - try again in a minute |
| `without a transparent background` | the service returned a normal picture - tell me and send the message |

Changing the engine later: `BG_REMOVER=cloudflare` (needs your own domain) or `BG_REMOVER=rembg` (on your PC) still work.
