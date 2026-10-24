# CardCrop

Drop in card photos, front or back, and every one comes out as a flat, squared, perspective-corrected card plus four square corner close-ups, ready for an eBay listing.

What changed in each version is in [CHANGELOG.md](CHANGELOG.md).

## Install as a Mac app

Any Python works to start the script. CardCrop runs on Python 3.12, because brand-new releases often lack packages the card reader needs, and if 3.12 is not on your Mac the script fetches it automatically with uv, leaving your other Python untouched. In Terminal:

```
cd ~/Documents/cardcrop
./build_mac_app.sh
```

It takes a few minutes the first time, checks itself, and puts **CardCrop** in your Applications folder; from then on you open it like any app, with no Terminal. After copying in new versions of the `.py` files, run the script again to rebuild. The app is built on your own Mac, so Gatekeeper treats it as yours and it opens without warnings.

## Run it from Terminal instead

Install Python 3.10 or newer from python.org (on Windows, tick "Add to PATH"), then double-click **Start CardCrop (Windows).bat** or **Start CardCrop (Mac).command**. The first launch builds a private environment in a `.venv` folder and takes a minute; after that it opens straight away. On a Mac the first launch may need right-click → Open to get past Gatekeeper.

From a terminal it is `pip install -r requirements.txt` and then `python app.py`.

## Workflow

Drop photos or a whole folder onto the window, and detection runs in the background while you work, so the queue is ready before you reach it. Each photo opens with the four yellow handles already on the card's corners, a check mark appears once it is exported, and an orange `!` marks a photo whose edges came out weak enough to deserve a look before you trust it.

**Three stages.** The rail on the left switches between **Shoot** (L), **Edit** (E) and **List** (Cmd+L); Cmd+K opens a command palette with everything the screens leave out (eBay account, review and publish, folders exported earlier, route, save folder, theme, text size). The sun or moon at the bottom switches light and dark, and the photo always sits on graphite whichever you choose.

**Edit.** The photo fills the canvas with the crop tools floating on its left (auto-detect, rotate, fit, free corners or card shape, snap, loupe, saved spots 1 to 4), the file and edge readout along the top, and the finished card with its four corners in the bottom right. The filmstrip underneath shows every photo as a tile with its side, grade and status (Exported, Needs price, eBay unpublished and so on), and **Carousel only** sits beside it. On the right: the batch counts (ready, need you, on eBay) with **Next ⚠**, the card (name, set, number, its file name, Front or Back, and the grade, set on the back), the price in large figures with **Use $…** for the live suggestion and ↻ to check again, and the title with copy buttons. **Crop**, **Tone**, **Lens** and **Output** open their settings in the same column; the arrow brings the card back. **Export and next** (Enter) and **All** stay at the bottom. A Near Mint card priced over $25 gains **CLEAN** after the number in its title.

**Shoot.** Live view fills the canvas, with LIVE and the camera's name top left, zoom top right, the last shot bottom left and rotate, match and reset bottom right. The column on the right holds aperture, shutter and ISO as large tiles, the rest of the camera settings, the grid and overlay options, which card and side comes next, and AF, the shutter and a jump to Edit. Without a camera it offers **Connect camera** instead.

**List.** Every card in the batch as one row: picture, name and number, set, grade, price (type it in; the suggestion under it fills it in when clicked), outputs, photo count and status. Filter by Ready, Needs you or On eBay, search by name or number, tick rows (or **Select ready**), and the bar at the bottom shows the count and total and sends them: **Upload N to eBay** or **Draft N to eBay** depending on the route, set from the Route menu, and **Instagram carousels** for the slides. Double-click a row to open that card in Edit.

**Store** (Cmd+Y) reads your eBay account through eBay's Trading API, with the sign-in you already have: sales over the last 60 days with their total, the last 7 days, orders paid but not shipped, active listings and what they add up to, and watchers; sales per day as a bar for each day; and three lists: Just listed, Recently sold (marked Ship when paid and waiting), and Most watched. It covers every listing on the account, not only ones made in CardCrop, shows your own photo when CardCrop made the listing, and double-clicking a row opens it on eBay. It refreshes when you open it if the last read is over ten minutes old; eBay only reports the last 60 days of sales here.

**Settings** (the last button on the rail, or Cmd+,) has four tabs. **Tracking** reads the output folder and eBay records, so it covers every card ever exported: cards and photos today, this week, the current streak and best day, a day-by-day grid going back up to a year, the split of conditions, English and Japanese, Pokémon, Yu-Gi-Oh! and One Piece, eras (WotC through Mega Evolution), price ranges with the total, average and median, and what is live, unpublished or drafted on eBay; 7 days, 30 days or All time narrows the breakdowns. **Output** holds format, hero, Instagram, auto-identify and the save folder; **eBay** the account, route, auto-upload and drafts template; **App** the theme, text size and the game you usually identify.

**Auto-upload.** The round upload button beside Export and next (also in List's Route menu and Cmd+K) turns it on. From then on, each card that is identified, graded, priced and exported on both sides goes up to eBay unpublished in the background as you move on to the next card, so at the end of a batch you only review and publish from List. Change a price or grade on a card that is already up and it is sent again as you move on. Nothing is ever published without you.

**Bulk (under $1)** is a built-in preset for the lowest tier: it writes only the front, the back and the hero (front and back side by side on a light background), as JPEGs, with no corner close-ups and no Instagram slides, and the listing text no longer mentions corner close-ups.

**Selecting.** Every list with tick boxes has All and None (List also has Ready). Uploads show a slim progress bar with the photo count, like 4/10, instead of a line of text.

**Publishing from List.** Cards already on eBay are never uploaded twice: ticking them shows **Publish N** instead, which asks once and puts them live. A photo upload that eBay answers with a server error (it happens under load) is retried a few times before the card is marked Failed; tick a failed card and upload again.

**English only.** Titles, item specifics and descriptions never carry Japanese text. A Japanese card whose English name CardCrop cannot work out (usually a Trainer) shows **Add the English name** on the card and counts as needing you until it has one.

**Yu-Gi-Oh! and One Piece.** The Identify window (I) has a game picker: Pokémon, Yu-Gi-Oh! or One Piece. Search by name, by the printed code (LOB-EN005, OP01-001) or both; a code alone is recognised whatever game is picked, and file names like `dark-magician-lob-en005` or `roronoa-zoro-op01-001` identify themselves. With One Piece picked, auto-identify reads the code at the bottom of the card; with Yu-Gi-Oh! picked, it reads the set code under the art. Card data comes from YGOPRODeck and the OPTCG API (One Piece's list is saved for a day; pictures are saved once), prices from those databases plus live eBay listings, and listings use the right game, manufacturer and title words.

**Messages** appear as a toast over the photo instead of pop-ups, so they never stop you working: they fade after a few seconds, errors and anything with Details stay until you close them. Pop-ups are kept for questions that need an answer.

**Text size:** Cmd+= larger, Cmd+- smaller, Cmd+0 back to the default; CardCrop remembers it, and the theme.

| Key | Action |
| --- | --- |
| Enter | Export this card and jump to the next unfinished one |
| R | Re-run auto-detect |
| T | Rotate the photo and the output 90° together |
| F | Fit the photo to the view |
| [ and ] | Previous / next photo |
| Arrows | Nudge the selected corner 1 px (Shift for 10 px) |
| B | Flip the photo between front and back |
| C | Drop a fresh card shape in the middle and switch to shape mode |
| M | Switch between corner mode and shape mode |
| 1 to 4 | Jump the outline to a saved spot |
| Cmd+1 to Cmd+4 | Save the current corners as that spot |
| I | Identify the card, or choose between several matches |
| Z | Change how much the loupe shows: about 8, 15 or 24 mm across |
| Cmd+Z / Shift+Cmd+Z | Undo / redo corner moves, rotations and re-detects |

Dragging a corner opens a loupe showing about 15 mm around it, with each edge drawn as a long dashed guide past the corner. Because cards have rounded corners, the true corner is the point in empty space where the two straight edges would meet, so you align each guide with the straight run of its edge a few millimetres away and the handle's crosshair lands where they cross, which is what makes the perspective warp come out square.

**Export all remaining** skips the clicking entirely and exports every unfinished photo with whatever detection found, so the fast path is to shoot a stack, drop the folder, press it, and then open only the `!` photos.

Each photo produces five files in the output folder:

```
charizard_front.png        flattened card
charizard_front_TL.png     top-left corner
charizard_front_TR.png     top-right
charizard_front_BL.png     bottom-left
charizard_front_BR.png     bottom-right
```

Files keep the source photo's name unless you give the card a name.


**Condition.** When the current photo is a back, a Condition row appears under the card name with NM, LP, MP, HP and DMG (Alt+1 to 5; click the lit one again to clear). The grade goes into the back's filenames, such as `lugia-v-185_03_back_LP.png` and its four corners, so you see it in the upload dialog without anything drawn on the photo, since eBay does not allow text on listing pictures. It also goes into the listing: the description states it, and the eBay drafts template gets Condition ID 4000 (ungraded) and the matching Card Condition grade. eBay has four ungraded grades, so DMG uses its lowest, Heavily played, and the description says Damaged. Fronts never show the row.

**Searching.** The Identify search accepts whatever you know: a name and a number (`lugia 185`, in either order), the full number (`185/195`), a name alone (`lugia v`, words in any order), or a bare number. If a typed total does not match the name, it trusts the name and number and searches every set. TCG Pocket's digital cards are left out.
## Corner mode and shape mode

Corner mode, the default whenever a card is detected, lets each corner move freely, which is what you want for correcting perspective. Shape mode locks the outline to a true 63 × 88 card: dragging a corner resizes from the opposite corner, holding Cmd resizes from the centre, dragging just outside a corner (the cursor turns into a curved arrow) rotates around the centre, with Shift snapping to whole degrees, dragging inside the outline moves it, and the arrow keys nudge the whole card. Pressing M in corner mode snaps the current outline to the nearest card rectangle; pressing it again frees the corners for fine perspective fixes. A photo where nothing was found opens in shape mode, and each photo remembers the mode you left it in.

## Saved spots

If you shoot from a fixed position, save the corners of a good card as a spot with Cmd+1 (or Shift+click a spot button), and from then on pressing 1 snaps the outline there on any photo. Spots are stored as positions within the frame, so they survive switching between RAW and JPEG, and they persist between launches. When detection finds nothing, the outline starts from the last card you exported if the photo is the same size, then from spot 1 if you have saved one, then from a plain card shape.

## Shooting tethered (Sony a6700)

CardCrop can drive the camera directly over USB through Sony's Camera Remote SDK, with live view, the shooting settings and the shutter inside the app, and every shot landing in the queue already detected.

**Once:** download the Camera Remote SDK for Mac from Sony and unzip it in Downloads (it must come from you, under Sony's licence), then run `bash tether/build_tether.sh` from the cardcrop folder. It compiles a small bridge program and installs it in `~/Library/Application Support/CardCrop/tether`, so rebuilding the app never disturbs it; `build_mac_app.sh` also runs it automatically when the SDK is in Downloads. It needs Apple's command line tools, and offers to install them if they are missing.

**On the camera:** turn on PC Remote with USB as the connection method (in the Network menu, under the PC Remote Function settings), plug the camera in, and quit Imaging Edge so it does not hold the camera.

**In CardCrop:**

| Key | Action |
| --- | --- |
| K | Connect or disconnect the camera |
| L | Live view on or off |
| A | Autofocus, with a green or orange confirmation on the live view |
| Space | Focus and shoot |
| O | Show or hide the card overlay |
| U | Move the overlay to the last detected card |
| G | Cycle the grid: thirds, thirds with diagonals, square, fine, diagonals, centre cross, off |
| T / Shift+T | Rotate the view right / left |
| Scroll, double-click | Magnify the live view up to 4x where you point; double-click again to reset |

Live view shows a card overlay, a dashed outline you shape directly on the picture: drag inside it to move it, drag a corner to resize it with the card proportions locked (Cmd resizes from the centre), and drag just outside a corner to rotate it. With **Follow shots** on, the overlay moves after every shot to where the card was actually detected, so it always reflects reality; the target button (U) does the same on demand, and reset puts a centred card back. While shooting, keys 1 to 4 recall overlay presets and Cmd+1 to 4 save them, separately from the editor's saved spots, and the card name and saved-spot rows are hidden so nothing on screen affects the export. The overlay sits under a grid whose pattern, colour, opacity and line weight you choose from the view row; all of it is remembered between sessions. Rotating the view turns the outline with it, and shots taken in a rotated view open in the editor turned the same way. The magnifier enlarges the live view image itself, which is lower resolution than the photo, so use it to check framing and rough focus rather than fine detail. Aperture, shutter, ISO, exposure, white balance with Kelvin, focus mode and area, file type and save destination are all set from the camera bar, which **Settings** folds away to give live view more room. The exposure mode follows the dial on the camera and is shown, not set.

Shots save to `~/Pictures/CardCrop Captures/<date>` and also to the camera's card unless you choose Mac only. With RAW+JPEG, CardCrop loads the RAW. A new shot opens for review straight away; Enter exports it, and once nothing is left in the queue CardCrop returns to live view for the next card, so the rhythm is Space, Enter, Space, Enter.



When a front opens, CardCrop reads the collector number printed at the bottom of the card (like `4/102` or `025/198`) and looks it up in TCGdex, a free card database covering English and Japanese sets. One match fills in the card name straight away; several matches (the same number exists in more than one set) put a note under Listing, and pressing I opens a picker with card images so you choose the right one. The picker also searches by name, so a card whose number will not read is still two keystrokes away. The back inherits the front's identification. Identification needs an internet connection; everything else in CardCrop works offline.

## Listings

Once a card is identified, the Listing panel shows an eBay title under 80 characters that you can edit, with buttons to copy the title and a description that lists the set details, the measured centering for both sides, and a note that the photos show the exact card. The title never claims a condition, since that is your call to make. Every export also saves `_listing.txt` and `_listing.json` next to the photos.

To list a batch at once, download eBay's drafts template once (Seller Hub > Reports > Uploads > Get template > Create drafts, category Pokémon Individual Cards, CSV), then choose **Drafts file for every exported card…** in the List stage's Route menu or Cmd+K and pick that file (CardCrop remembers it). CardCrop fills every column it recognises (SKU, category, title, description, game, card name, character, set, number, rarity, language and the rest) for every saved listing and tells you which required columns it left for you, normally condition and price. Upload the result in Seller Hub > Reports > Uploads, then add each card's photos as you finish its draft; the drafts template allows photos to be added at that stage.

## Hero image

Named cards also get `_01_hero`, a square first photo of the front and back side by side, cut to their rounded shape on a clean light, dark or black background with a soft shadow. It contains no text, borders, logos or watermarks, because eBay's picture policy prohibits them.

## Naming and listing order

Type a name in the Card field and press Enter, and the export goes into a folder of that name with every file numbered in listing order, so dragging the folder's contents into eBay drops them in sequence:

```
charizard-base1-4/
  charizard-base1-4_01_hero.png
  charizard-base1-4_02_front.png
  charizard-base1-4_03_back.png
  charizard-base1-4_04_front_TL.png ... _07_front_BR.png
  charizard-base1-4_08_back_TL.png  ... _11_back_BR.png
  charizard-base1-4_listing.txt
```

Corners are numbered in reading order, top left, top right, bottom left, bottom right, so in eBay's uploader the bottom-left corner sits before the bottom-right.

After you export a named front, the next photo opens as that card's back with the name already filled, so the pair costs one typed name and two presses of Enter. A back-only listing is one press of B.

## The card in 3D

The 3D tab in the left rail (or D in Edit, or the cube in the Edit tool rail) holds the card. It pairs a front with its back by name, or, for a back not named yet, with the photo right after the front. Pick any card from the menu at the top left: this batch first, then cards exported earlier. It shows the front and back photos on a real rounded card with a thin white edge, lit, with a foil shine that moves with the angle.

- Drag to turn it any way, all the way round. Let go mid-drag and it glides on and eases to a stop. Scroll to zoom, double-click to reset to face-on (0° turn, 0° tilt).
- Keys while the card has focus: S spins 360, F flips, R resets, Space starts or stops the turntable, the arrow keys fling it left or right.
- Moves: Spin 360, Flip (F), Front, Back, Sway (tilts either side so the foil sweeps across), Reset, and Turntable (Space), which eases up to speed and eases down when turned off.
- Angle: type a Turn and a Tilt in degrees and press Return, or use 15°, 30°, 45°. It always takes the short way round.
- Foil: Holo (whole face), Art (the art window only, like a classic holo), Reverse (everything but the art), or Off, with a strength slider. Backs never get foil.
- Export MP4 renders a full 360° turn frame by frame at an exact size, so it is smooth whatever the screen does: Steady loop (seamless, for posts that loop), Eased pausing on the front, or Sway then a full turn; 2 to 30 seconds; Square 1080, Portrait 1080 × 1350, Story 1080 × 1920 or Wide 1920 × 1080; dark, light, white or lime background. H.264 at 30 frames a second, so it plays in QuickTime, Instagram and eBay.
- Record captures whatever you do in the window (drags, moves, the turntable) at the last export size until you press Stop, and saves it in the card's folder.

The view uses this session's straightened shots with the current tone; for a card exported earlier it finds the card again inside the exported photos.

## Centering

Under the result preview the app reads the border widths and prints the centering, for example `L/R 55/45 · T/B 52/48`, with a dashed green frame on the preview marking the printed edge it measured against, so a wrong reading is obvious at a glance. Copy puts the line on the clipboard for the listing, and named exports save it beside the images. Full-art and borderless cards report no border found instead of a guess, and since the number is only as good as the corners, check the frame on any card where you dragged them.

## When detection misses

On a plain dark background, detection also looks at colour, not only brightness, so a dark border on a dark background (a Pokémon back's navy on black) is found at the card's true edge instead of at the artwork inside it. On a busy background this extra step stays out of the way.


If no card is found, the outline starts from the corners of the last card you exported whenever the photo is the same size, so shooting from a fixed spot turns a miss into a small nudge; otherwise it starts as an upright card shape in the middle of the frame, and C resets to that shape at any time. Sideways cards come out upright automatically until you rotate by hand; once you press T the editor view turns with the output, so the result always matches what you see. Auto-rotate can be switched off in the settings.

## Formats

Input covers JPG, PNG, TIFF, WebP, HEIC, and Sony **.ARW** along with other camera RAW (CR2, CR3, NEF, RAF, RW2, ORF, DNG). RAW is decoded at 16 bits with the white balance you shot with, and the 16 bits survive the warp, so nothing is rounded off until the file is written.

| Output | Notes |
| --- | --- |
| PNG lossless 8-bit | Default; zero compression loss and accepted by eBay |
| PNG lossless 16-bit | Full RAW depth; large files, for archiving or editing |
| TIFF lossless 16-bit | Same, for Lightroom or Photoshop |
| TIFF 32-bit float | Floating point for heavy grading in Photoshop; no visible gain over 16-bit for listings |
| JPEG max quality 4:4:4 | Quality 100 with chroma subsampling off, so colour edges and holo stay crisp |

## Settings

**Edge margin**, 20 px by default, keeps that much of the surrounding photo outside the detected edge on every side, measured in native output pixels, so a corner handle sitting a hair inside the true edge never shaves the card, and the corner crops carry the same band. **Corner crop** sets the size of each corner square as a percentage of card width; 20 to 25% makes a tighter close-up for showing whitening. **Lens** applies a measured profile for your lens, taken from the Lensfun database: the Sony E 30mm F3.5 Macro (SEL30M35) is built in, correcting both its slight distortion and its red and blue colour fringing toward the frame edges. Choose **RAW only** when the camera's own JPEGs already have Distortion Comp. switched on, or **all files** when it is off. The profile was measured at normal distances, so at the closest macro distances a little residual bowing can remain, which **Extra distortion (manual)** trims on top; that slider also straightens bowing from lenses without a profile. Phone photos are already corrected and need neither. From the command line, `--lens-profile sel30m35` does the same. **Upscale corners to 1600 px**, on by default, enlarges each corner with Lanczos resampling and a light edge restore so eBay displays it at full size rather than stretching a small file itself. It cannot add detail the camera never captured, so the real lever for sharp corners is filling more of the frame with the card when you shoot. **Force standard card shape** outputs exactly 63 × 88 mm proportions; switch it off for oversized or graded slab photos.

## Adjust

Exposure (±5 EV), contrast, highlights, shadows, saturation, warmth, and sharpen apply to the flattened card and its corners after the warp, computed in 32-bit float, so a 16-bit RAW keeps its full depth through the edits. Exposure and warmth work in linear light the way a raw converter applies them, highlights, shadows, and contrast move luminance while leaving hue alone, and sharpen is a small-radius unsharp mask meant for print dots and edges rather than halos. The sliders apply to every photo in the session and are remembered between launches, and Reset returns them all to zero, at which point the output is the untouched warp.

## Shooting for clean detection

Put the card on a background that contrasts with its border: a black mat under yellow-bordered Pokemon cards, a light surface under dark-bordered ones. Detection finds the card by its silhouette, so a black-bordered card on a black mat is the one case it reliably misses, and that is exactly when it shows `!`. Shooting from slightly above with soft light keeps the shadow off the edge.

## Batch from the terminal

```
python cli.py "D:\photos\today" -o "D:\photos\out" --format jpg
```

It prints the edge confidence for each photo and lists any worth checking by hand.


**Instagram carousel.** With **Instagram carousel for fronts** on (Output tab), exporting a named front also writes three slides into an `instagram` folder inside the card's folder, so the eBay photos stay separate. Every slide is 4:5 at 9374 × 11718 px, 300 dpi, JPEG quality 95. Slide 1 is the whole card at 5074 × 7071 on #F2F2F2, placed at x 2155, y 2323 exactly as in the template artboard, with rounded corners masked onto the background. Slides 2 and 3 are one close-up split down the middle, rendered from a single mapping so the swipe is seamless. **Close-up… (P)** opens the framing: drag the box, scroll or use the slider to zoom, and tick the box to make that framing the default. If the card is already exported, saving rewrites its slides straight away. The slides render in the background, a few seconds per card.

**Carousel only** (the switch under Clear list) is the post-editing mode: while it is on, every photo, whether dragged in, added or already waiting in the list, writes only its three Instagram slides when you press Enter or Export all, with no eBay files and no tone or lens changes. Each photo shows `writing…` and then `slides saved` in the list, so you can see that it went through. **Carousels from edited photos** (Output tab) switches the mode on for you and is for photos you have already finished elsewhere. Choose them and they join the list marked `IG ·`. CardCrop finds the card, removes the background, black or otherwise, and writes only the three Instagram slides into `instagram` in the output folder. No eBay files are written and no tone or lens settings are applied, so your edits are never doubled. Check the corners as usual, press P to frame the close-up, then Enter for one photo or Export all for the batch.

**Presets** sit at the top of **Tone** and cover every crop, adjust, lens and output setting at once. Three are built in: eBay listing (default), No tone edits, and Already edited photos, which also turns lens correction off. **Save…** stores the current settings under a name of your own, marked with a star. **Delete** removes one of yours; the built-in presets cannot be deleted.

**Corner close-ups** can be switched off with **Export corner close-ups** at the top of the Crop tab, for when you only want the flattened card, for example alongside a carousel post. The corner previews in the Result panel hide while it is off, and presets remember the choice.

**Photos already named for their card.** A file named the way CardCrop names cards, such as `thundurus-ex-bwp-bw81.jpg` or `lugia-v-swsh12-185-ja.png` (name, TCGdex set code, number, and `-ja` for Japanese), is identified straight from its name with no number reading. Endings such as `_02_front`, `_IG_1`, ` edited` or ` final` are ignored. Promo cards show their number without a set total, as printed.

## Condition report

Made only when you ask, never for every card. The Reports tab in the left rail is the home for them:

- Calibrate first. The first report asks for it: CardCrop measures the cards you have already graded (your eBay listings, live and sold in the last 60 days, plus any export folders you add) and fits its scoring to your grades. It needs at least 20 graded cards, 4 of them below Near Mint, and shows how often it agreed with you on cards it was not fitted on. Recalibrate whenever you have listed more.

- My cards: this batch, every card in the save folder, and any card folders you add (Add folders…). Pick one to preview its report, or tick several and Make reports; each is added as the card's last listing photo. Remove from listing takes one off again.
- Live on eBay: your live listings (from Store's last refresh). Add video renders a 360° turn of the card (read from the listing's photos, shown in the 3D tab while it renders) with your last 3D export settings, uploads it and attaches it to the listing; tick several and Add videos to do them one after another. A listing has one video, so a new one replaces the old. eBay currently plays listing videos only in its iPhone and Android apps.
- Reports on live listings: Make report downloads the listing's photos, finds the front and back among them (skipping the side-by-side hero and close-ups), and draws the report; Add to live listing uploads it and makes it the listing's last photo, live. Tick several and Add reports to do them in one go (it asks first). CardCrop's own listings are changed through their inventory record, others by revising the listing's pictures.

Elsewhere:

- Edit: Condition report (under the condition buttons, or Ctrl+R) for the card you are on. A preview opens; Add to listing photos saves it as the card's last photo (12), so it uploads with the listing.
- Shoot: Report on the last-shot panel, for the card you just photographed.
- List: select cards and press Condition reports on the action bar; each selected card gets its report as its last listing photo.
- Cmd+K: "Condition report for this card".
- List exported folders on eBay: Condition reports for the ticked folders, before uploading them.

It works for cards in this batch and for cards exported earlier (it finds the card again in the exported photos).

The report scores the card the way graders think: every card starts at 100 points and loses some for each flaw found. One segmented bar shows the score against the five conditions (DMG below 30, HP 30, MP 50, LP 70, NM 85 and up), and a row per category shows what was taken off and why:

- Centering (up to 2 points per step off perfect): the measured ratios for front and back.
- Corners (3 per step) and Edges (2.5 per step): sharp or clean, light wear, wear or heavy wear, and which side. Wear means light specks where the border colour should be, measured against the card's own edge, so the thin line of the cut card stock never counts.
- Surface (2.5 per step): backs only. Every back of a game is the same print, so each one is compared with a clean reference CardCrop builds from the backs you report on (it needs three first). Fronts are not judged, since their artwork differs.

If the report lands in a different condition from the one you set, Edit says so under the condition buttons (and a batch of reports lists them), so the listing and its report never disagree. The image itself carries no grade, only the score and the condition band.

Small flaws below what a buyer would notice are left out, but obvious wear is reported as wear, matching what the photos already show. After a report, Edit shows the same findings in a line under the condition buttons.

## Market: price movers and alerts

The Market tab (Shift+Cmd+M) prices every card you have on eBay and shows how the market moved: CardCrop's own listings (live or unpublished) and every other active listing in your store, however it was made. A scan reads the whole store fresh first. Listings made outside CardCrop are identified from their titles (name, number and set size, such as 039/084); when the card database finds that exact card its TCGplayer and Cardmarket prices are used, otherwise eBay's asking prices for the title's name and number. Use $x changes those listings' prices on eBay as well. Cards only exported, or sold, are left out.

- **Top movers, highest first**: each card with your price, the market price, its change Today or over 7 days, and a bar per scan. On eBay shows everything listed; Live narrows it to published listings.
- **Price alerts**: cards whose market price is more than your alert percentage away from your asking price (under or over market), or that moved that much in a day. Each has Use $x, which sets your price to the market suggestion and, when the card is on eBay (live or unpublished), changes the listing's price there too; Sold on eBay, which opens eBay's sold listings for that exact card so you can check what it really goes for; and Listing.
- **The nightly scan** runs at the hour you pick (12:00 AM by default, or Off). CardCrop has to be open, even in the background, and the Mac awake; a missed night runs as soon as CardCrop opens again. When it finds cards to check, a lime dot appears on Market and macOS shows a notification. Scan now runs one whenever you like, and Stop ends one early.
- **Where the numbers come from**: eBay does not let sellers read sold prices across the market, so the market price is the same suggestion CardCrop gives in Edit (the lower quarter of eBay's live asking prices for that exact card, or TCGplayer's market price, which TCGplayer works out from its recent sales). Changes are measured on TCGplayer's market price where there is one, from CardCrop's own daily snapshots; until two days of scans exist, Cardmarket's 1-day against 7-day sold average stands in.

## Store listings

Store has two views. Overview is the dashboard, and Listings is every active listing, editable. Change quantity or price in a row and press Return, or pick a listing to edit its title, price, quantity, condition and best offer (auto-accept and auto-decline), then Save to eBay. Video, Report, Open on eBay and End listing are under the editor. Prices typed anywhere in CardCrop (Market, List, Store) go to the live listing.

## Store traffic

The Traffic panel in Store mirrors Seller Hub's Traffic card for the last 30 days: listing impressions, click-through rate (clicks from search ÷ times shown in search), listing page views and sales conversion rate (items sold ÷ page views), each with a bar per day and its change on the 30 days before (percent for counts, points for rates). Where views came from splits page views into On eBay and External (off eBay), with the eBay part (search, other eBay pages, your store, direct) in the tooltip; eBay's traffic report does not separate Promoted Listings, so those views sit inside the eBay sources. It reads eBay's Analytics API, which needs one more read-only permission than listing does: the first time, the panel shows Reconnect eBay; sign in once and it fills in from then on. Figures are in Pacific time like Seller Hub's, and may differ from it by a rounding or a day at the edges.

## Listing on eBay (unpublished until you publish)

**One-time setup** (Cmd+K > eBay account…, or List > Route > eBay account…): paste your Production **App ID** and **RuName**, and type the **Cert ID**, which goes into your Mac's Keychain rather than any file. Press **Open eBay sign-in**, sign in and agree in the browser, then copy the whole address of the page that says *Authorization successfully completed* and paste it in, then **Finish sign-in**. The code in that address lasts only a few minutes. CardCrop then stays signed in for about 18 months. Enter your ship-from ZIP, press **Load my policies from eBay**, choose your shipping, return and payment policies, and Save. Your account needs business policies; Seller Hub > Account > Business policies creates them.

**Per card:** export the front and the back, set the condition on the back, identify it, enter a **Price**, and press **Upload to eBay**. CardCrop uploads the photos in their numbered order (as high-quality JPEGs, 4000 px on the long side, since eBay limits file size), then creates the listing with the title, item specifics, ungraded condition and description. Nothing is live yet. Uploading the same card again updates that unpublished listing in place, so fix and re-upload freely.

**Route.** The List stage sends the ticked cards one of two ways, chosen in its Route menu: **Upload** (unpublished listings through the API, put live from Review and publish) or **Draft** (photos up, then a Seller Hub drafts file). The same menu holds Review and publish…, Add exported folders…, the drafts file for every exported card, and eBay account…; all of them are in Cmd+K too. The folder list makes the same route its dark button.

**Review and publish…** lists everything uploaded through the API (cards sent as Seller Hub drafts are finished in Seller Hub, so they are not listed here). Tick what you have checked and press **Publish selected** to put it live; double-click a live one to open it on eBay. **Remove selected from eBay** deletes unpublished listings without touching your files. A record of uploads is kept in `ebay_uploads.json` in the output folder.

**Listing folders you exported earlier**, with no shooting or exporting: drop a card folder, or a folder of card folders, onto the window, or use **Add exported folders…** in Cmd+K or the List stage's Route menu. Each folder is one card, and its photos upload in file-name order (the `instagram` folder is skipped). The card is read from a saved listing in the folder or from slug-style names such as `thundurus-ex-bwp-bw81`, and the condition from names such as `_back_LP`. Anything missing shows in the table: double-click a card to search for it, pick a condition, enter prices, tick the rows and upload. Everything arrives unpublished, for **Review and publish…**. Dropping loose photos, or folders that are not exports, still adds them to the editor as before.

**Seller Hub drafts with photos** (recommended): **Draft N to eBay** in the List stage (with the route set to drafts), or **Make Seller Hub drafts** in the folder list, uploads each card's photos to eBay's picture hosting and writes `ebay_drafts_<date>.csv` into the output folder, filled from eBay's own Create drafts template (choose it once under Account… > Seller Hub drafts; get it from Seller Hub > Reports > Uploads > Get template > Create new drafts). Upload that file in Seller Hub > Reports > Uploads and every card appears in your eBay Drafts with its photos, title, item specifics, condition, price, policies and description, to check and list from eBay. eBay gives uploaded photos an expiry date if no listing uses them, so upload the file the same day. eBay's API cannot create Seller Hub drafts directly, which is why this goes through the file.

**Package** (Account…): weight in ounces and size in inches, sent with every listing. Calculated shipping policies need them; without them eBay refuses to publish (error 25020).

**Drafts.** **Make Seller Hub drafts** uploads the photos to eBay, fills your Create new drafts template (choose it once; Seller Hub > Reports > Uploads > Get template > Listings > Create new drafts), then shows the finished file in Finder and opens Seller Hub's Uploads page: press Upload template and choose it, and the cards appear in your Drafts with photos. That last step cannot be automated: eBay's Feed API accepts the same file but rejects the Draft action ("Unable to find Task Action Id for task Draft"), so only Seller Hub's own button creates drafts. To skip it, use **Upload unpublished (API)** and approve from **Review and publish…** instead. The drafts template only accepts New or Used, so set the card grade in each draft before listing.

**Price suggestions, checked live.** When a card is identified, CardCrop searches eBay right then for fixed-price, ungraded listings of the same card (titles must carry its number; graded slabs, lots and proxies are skipped) and reads TCGplayer and Cardmarket prices fresh from the card database. The suggestion is the lower quarter of eBay's current asking prices, where cards tend to sell, rounded to .99; with fewer than three comparable eBay listings it falls back to TCGplayer's market price. **Use $…** fills the price, ↻ checks again, and in the folder list the suggestion fills any empty price automatically. eBay's search needs only your App ID and Cert ID. Asking prices are not sold prices; eBay keeps sold data for approved partners only.

**Japanese cards in English.** With Japanese chosen in the Identify search, type English as usual: `lugia v`, `umbreon ex 93`, `mew ex 151/165`. CardCrop turns the English name into the Pokédex number, finds the Japanese cards for it (and, since many Japanese cards carry no Pokédex number, also searches by the Japanese name it learns along the way, so ルギアV is found from `lugia v`). Results show the English name with the printed one beside it. The listing title, item specifics, folder name and price search all use the English name and the set code (for example *Mew ex 151/165 SV2a Double Rare Japanese Pokemon TCG Card*), since the set names are in Japanese. Trainer and energy cards have no Pokédex number; find those by their number, like `151/165`.