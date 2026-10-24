# CardCrop changelog

CardCrop started as a cropping tool and became a seller's workstation: shoot, straighten, identify, price, list, report on condition and watch the market, all in one Mac app. Versions follow the usual scheme, so a whole number marks a change in what the app is, the middle number a new feature set, and the last a round of fixes.

The current version is **3.14.0**. Newest first.

Dates before 16 October 2026 are approximate: those early rounds were not logged as they happened and are reconstructed from the code.

---

## 3.14.0 · Shipments redesigned: inbound and outbound, local pickup · 24 Oct 2026

- The package page leads with where it is, in a card after eBay's: a kicker (↗ OUTBOUND or ↙ INBOUND, and shipped to the buyer, on its way to you, delivered, label created or local pickup), a headline (Arrives by, Delivered on, or the stage), the last location, and the clickable status bar. Below it the nickname on one line, the number with Copy, Carrier and Open, the eBay sale with its title cut short, and the shipment history as two columns, date and time on the left, what happened and where on the right, in smaller type.
- Inbound and outbound: your eBay sales go out, numbers added by hand come in unless you pick otherwise when adding, and Mark inbound or Mark outbound switches it. Every row carries an OUT or IN tag.
- Local pickup: eBay orders picked up locally come in by their order even without tracking, with a two-step bar (Awaiting pickup, Picked up) that eBay's pickup status fills in; Mark local pickup turns any package into one, and its bar sets Picked up by hand.
- A label USPS has not scanned yet reads as Label created, not scanned yet, instead of an error; errors are tidied to one line, and Check all ends with one short notice (checked, not scanned yet, could not be read). Carrier changes a package's carrier by hand; a later eBay sync leaves your choice alone.
- List rows are tiles, with the nickname cut to one line, a smaller second line and the stage bar. eBay nicknames are cut at 30 characters.
- The window opens at 2000 by 1177 points, fitted to the screen, and remembers the size and place you leave it at.

## 3.13.0 · Shipments: status bars, eBay orders, USPS without a key · 24 Oct 2026

- Every package has a five-stage status bar (Label created, Shipped, In transit, Out for delivery, Delivered) on its row in the list and, larger and labelled, on its page. Click a stage there to set the status by hand; it is logged in the timeline, and a USPS scan newer than your mark takes over again.
- Sync eBay works: it reads your orders from the last 90 days with GetOrders, which carries the tracking numbers that My eBay Selling leaves out, with eBay's own carrier for each. It also runs on its own when the app opens and every 30 minutes.
- USPS scans without a developer key: USPS turns away programs that ask for its tracking page directly, so CardCrop now loads the page in a hidden built-in browser, lets it finish, and reads the history off it, one package at a time. A USPS API key, when given, is used instead. The app bundles Qt WebEngine for this, so it is larger.
- The list's second line is smaller, every button on the page is one height with nothing clipped, and the empty message is centred. The window opens 1000 points wide and remembers the size and place you leave it at. Shipments were already kept in CardCrop's data folder, so they last through closes and rebuilds.

## 3.12.0 · Shipments · 24 Oct 2026

- A Ship page on the rail (Shift+Cmd+S): every eBay sale with a tracking number joins it on its own whenever the Store reads your sales (or with Sync eBay), and Add tracking takes any number by hand with a nickname. Both kinds can be renamed, archived and deleted; numbers added by hand can be corrected, which starts their scans over. A nickname you give an eBay package stays through later syncs.
- Each package shows its USPS scans as a timeline, newest first, merged with what happened on the Mac (sold, imported, added, renamed, corrected), the status in large type, the expected delivery, and Open on USPS for the carrier's own page (UPS, FedEx and DHL numbers link to theirs). Copy puts the number on the clipboard.
- Scans come from USPS's tracking API with your own free developer app's Consumer Key and Secret (USPS API… on the page). Packages still moving are checked every 30 minutes while CardCrop is open, or with Check all and Check now; errors show on the package instead of stopping the rest. Filters for Moving, Delivered, Archived and All, and a search by nickname, number or buyer.

## 3.11.0 · Transparent PNGs, curled cards straightened, the lens on Shoot · 23 Oct 2026

- Two more output formats: PNG 32-bit (8 bits a channel plus transparency) and PNG 64-bit (16 bits a channel plus transparency). PNG stores at most 16 bits a channel, so the extra 8 or 16 bits a pixel are the alpha: the band of photo around the card and the corners past its own rounding are clear, and the card is opaque with an anti-aliased edge. Corner close-ups and the hero stay opaque. The phone's Export options list them too.
- The lens profile and the manual distortion slider moved to the Shoot tab, under View. Lens detail, an export step, stays in Edit's Lens section.
- Straighten curled cards, in Edit > Crop and on by default. Measured on 74 of your SEL30M35 RAWs from 17 to 23 October: the lens bows a frame-filling card's edges by about a pixel, while the cards themselves curl, caving or bulging their sides by up to 17 px, differently on every card, and a four-corner warp keeps that bow. Each side's leftover curve is now measured after the warp, to a fraction of a pixel, and the four curves are blended across the card so every side comes out straight and the inside follows smoothly. On eight of your curled cards, sides that bowed 9 to 17 px came out within about a pixel, most under half, for about a tenth of a second a card. Corners you set by hand stay where you put them; a flat card is untouched; live view skips it.
- Measure from session, beside the lens list: fits one lens distortion to the straight sides of the cards in the session's photos, keeping only sides read cleanly to within a pixel. It is applied only when one correction straightens the cards across photos; when the bow changes card to card, as it does on your shots, it says the cards are curling, points to Straighten curled cards and changes nothing. An applied measurement becomes the Measured choice in the lens list, keeps the base profile's colour-fringe correction, applies only to the kind of file it was measured on, and Forget drops it.

## 3.10.0 · Level · 23 Oct 2026

- The phone's Surface sheet has Level: the phone lies on the mat, then on the camera's rear screen, each twice with the phone turned 180° between, and the Mac works out how far the mat sits from parallel with the sensor. Turning the phone cancels its own lean, the camera bump's included, and measuring the camera as well as the mat means a sloped desk under a stand that slopes with it reads level, as the photo does.
- The result comes back in large type: the tilt in degrees, green to 0.3°, amber to 0.8°, red past it, and how many millimetres to raise which edge of the mat across the width you give. If the two halves of the phone's lean disagree, the phone moved or was not turned cleanly, and it asks for a fresh reading instead of trusting it.
- The Mac's status bar carries the reading as a badge, and beside it the same tilt measured from the current card's own four edges when the photo's EXIF gives its focal length, so the phone's number can be checked against the photos. Nothing is warped by it: every crop already straightens the card by its own edges, and tilt costs focus and even light, which only shimming fixes.
- The session file records the level it was shot at.

## 3.9.0 · Surface calibration · 23 Oct 2026

- The phone's Shoot tab has Surface: clear the mat, tap Shoot empty surface, and the Mac keeps that photo of the surface. From then on every card is also found as what differs from it, alongside the edge search, which holds a dark border on a dark mat where edges alone are faint; the edges still place the corners exactly. A photo framed differently (another aspect) ignores it. Shoot it again whenever the camera, zoom or lights move; Clear forgets it.
- The same photo reads the light: each corner of the surface against the middle, in percent, green when even, amber with some falloff, red when the edges are much darker.

## 3.8.9 · Hero sides, a tidier Output page · 23 Oct 2026

- Back in hero becomes Hero shows: Front and back, Front only or Back only, beside the background choice and greyed with it when the hero is off. A side asked for and missing lets the other stand in. Unticking Back in hero in 3.8.8 carries over as Front only. The phone's Export options has the same choice.
- Settings > Output is grouped under Format, Hero, Instagram, Identify and Save to, with the hero's two choices on one row and the carousel's two buttons on another.

## 3.8.8 · The 360° video to the phone, Back in hero · 23 Oct 2026

- A card's Both sides page on the phone has Save video: the Mac renders the 360° video with your 3D export settings into the card's folder, the phone fetches it as soon as it is done, and one tap on Save opens the share sheet for Save Video. Save to phone lists the video too once it exists.
- Back in hero, under Hero first photo in Export (and in the phone's Export options): untick it and the hero shows the front alone.
- Condition report is gone from the phone's Review cards and Both sides page until centering reports come to the phone.

## 3.8.7 · Exported corners fit the card, Carousel only lets go · 23 Oct 2026

- The hero and the carousel's first slide cut the card to its own corner radius, read from the photo, instead of a fixed one. The carousel's was smaller than a real card's (about 2.4 mm), so the mat showed as a black sliver round every corner, and any rounder card (Carddass) showed more. The 3D card reads its radius the same way.
- A photo marked Carousel only (from an earlier session, or exported while the mode was on) stayed carousel only after the Carousel only button went off, so Enter kept writing slides instead of the eBay files. The button now decides for every photo when it exports, turning it off clears the mark from all of them, and a session opened with it off clears it too.

## 3.8.6 · Carousel off means off, corners read right, video to both · 23 Oct 2026

- Unticking the Instagram carousel now stops it. A card's full-size copy for the slides was kept from any render made while the box was ticked and written by the next export whatever the box said; it is now kept only while the box is ticked, and Export all writes slides only then. Slides already in a card's instagram folder stay until you delete them.
- The 3D card's corner radius is read against the card's own edge colour beside each corner, not a point deep in the artwork, which on many cards never looked different enough from the background to count, so the standard corner stayed and the background showed as black slivers. Any card rounder than standard now gets its own radius, a background margin left by a loose crop is taken off, and the rounder corners decide.
- A 3D video recorded on the phone saves to the phone and to the Mac's Videos in one tap (Save), with Mac only beside it.

## 3.8.5 · Export from the phone, 3D corners that fit · 23 Oct 2026

- Review on the phone has Options, the Mac's Export settings in one sheet: format, hero and its background, corner close-ups and their crop, upscaling, and the Instagram carousel. Changes go through the Mac's own controls, so they stick.
- A card's Both sides page has Save to phone, which fetches the exported photos at full size (listing, carousel, corners, each group ticked or not) and hands them to the share sheet, where Save Image puts them in Photos. PNG and TIFF exports come over as full-size JPEGs, any transparent edge laid on white.
- Carousel on the same page frames the close-up for slides two and three as the Mac's dialog does: drag the 8:5 frame over the front, set its width from 20 to 100%, and keep it for this card or as the default. An exported card writes its slides straight away.
- The 3D card, on the Mac and the phone, reads its corner radius from the photos, so a card with large rounded corners (Carddass, some Japanese promos) no longer shows black wedges where a standard corner would be.

## 3.8.4 · Pair shooting keeps its pairs · 23 Oct 2026

- A front left waiting for its back could go stale (exported, removed, or made a back in Fronts and backs, or picked by Next up's Back), and the next shot was then filed as that old card's back, so shooting both sides never opened the new card in Edit. A shot now starts a card of its own whenever the front it would join is no longer waiting, and Fronts and backs clears whatever was waiting.
- Next up's Back joins only a front still to export that has no back yet; with none, it says so on screen and stays on Front, instead of tying the next shot to an exported card.

## 3.8.3 · One centering report a listing, a centering icon · 23 Oct 2026

- A listing carries one centering report: publishing again puts the new report in place of the old one on eBay instead of adding a second. A listing row in Store rings its report icon in lime once the report is up, as the video icon does.
- The Condition button is gone from the Store listing editor; Centering takes its place.
- The report icon is now four corner frames round a crosshair, on the rail's Reports, each listing row and the editor's Centering button.

## 3.8.2 · Centering buttons in two even rows · 22 Oct 2026

- Find again, Save, Export and Publish sit in two even rows, all one height, instead of one crowded row where two overlapped and Publish stood taller than the rest.

## 3.8.1 · Centering report: export as an image, publish to the listing · 22 Oct 2026

- Export saves the report as an image in the card's folder under reports, where it is never taken for a listing photo (a report saved beside the photos would have gone up with the next upload).
- Publish adds the report as the card's last listing photo (card_13_centering.jpg, after the condition report): every upload takes it, and when the card is live on eBay it is added to the live listing straight away. Publishing again asks first, since eBay keeps both.
- The Export button no longer clips its label.
- Add a centering report to any live listing from Store: the Centering button in a listing's editor, or the report icon on its row, opens it in Reports, from the card's exported photos when CardCrop has them, else the front and back found among the listing's own photos on eBay. Set the guides, and Publish adds the report to that listing.

## 3.8.0 · Centering for grading · 22 Oct 2026

- Reports opens on Centering, with the listing condition reports one click away beside it. Pick a card and its front or back: green guides sit on the card's cut edge and blue ones on the printed frame, found for you and then yours to set. Drag a line, type its position, or nudge it with the arrow keys (Shift ten pixels, Alt a tenth); turn either set to follow a crooked cut or print; zoom with the wheel or a pinch, jump to any corner, pan by dragging, double-click to fit.
- The splits as you move them (45.62T / 54.38B, 46.33L / 53.67R), each marked Pristine (52/48 or better), Pass, or the grade it caps at, and the expected grade for the side and for the card, against PSA's published centering limits (front 55/45, back 75/25 for a 10).
- Cert number, predicted and actual grade beside it. Everything saves with the card as it changes (card_centering.json), and Export writes a one-page report of both sides to the card's folder: the photos with their guides, the splits, the borders in pixels, the grade.

## 3.7.17 · The top loader stays when you grab the card · 22 Oct 2026

- Grabbing the card in 3D while it was being sleeved or loaded (or starting a camera move or a focus pull then) stopped the move, and with it the holders the move was placing, so the top loader vanished and the card sat bare. A move cut short now lands the card in the holder it was heading for, and the holder buttons follow.

## 3.7.16 · A second copy of a live card gets a listing of its own · 22 Oct 2026

- Uploading a card whose SKU was already live on eBay (another copy of the same card, listed earlier or outside CardCrop's records) wrote this copy onto that live listing, replacing its photos, title and quantity, and Publish then reported it live because eBay answers a publish of a live offer with the same listing. Now the upload checks eBay first: when that SKU is live, this copy gets its own SKU (pikachu-1-2, -3 and so on) and its own listing, and the live one is left exactly as it was, with its record kept beside the new one.
- Publish refuses an offer that is already live and says which listing it is, rather than calling it newly published.
- In List, a card already live or sold can be ticked and uploaded as another copy; CardCrop asks first. Price and store category changes from CardCrop go to the copy's own SKU.

## 3.7.15 · Fronts and backs: drag across the whole list, or pick from a menu · 22 Oct 2026

- Dragging a photo lifts it: its tile fades, the full-size picture travels with the pointer, and holding it near the top or bottom of the list scrolls toward any front off screen, faster the closer to the edge.
- Right-click any photo for Make this a front or back, Make this the back of (every front by number and card), and Unpair, so a pair can be made without dragging at all.

## 3.7.14 · Fronts and backs that apply, stay open, and pair by dragging · 22 Oct 2026

- Fronts and backs changed nothing: the check for Apply asked the window for a constant it does not carry, which failed the moment the window closed, so the sides were never written. Apply now runs inside the window.
- The window stays open after Apply while the fronts are read, each tile naming its card as it comes in (reading…, then the card, or pick the card), and offers Close only when every front is done; it cannot be closed or escaped while reading.
- Drag a photo onto another to pair them: the one dropped on becomes the front, the dragged one its back. Each back tile says whose back it is (back of 4), or no front in orange; pairs already made carry into the window, and Clear pairs drops the hand-made ones.

## 3.7.13 · Fronts and backs put right in one go, and Identify on demand · 22 Oct 2026

- Fronts and backs (Edit, under Front and Back; the strip's right-click menu; Cmd+K) shows every photo still to export as a tile in shooting order. Click a tile to switch it; Find backs marks backs by look (a game's backs are one design, so they match each other, and Pokemon's have a blue border), and it picked all 11 of the last shoot's photos correctly; Alternate and All fronts are there for the simple cases. Apply pairs each back with the front before it, names it after that front, and reads again every front whose card is unknown or that was not a front before; names you typed are kept, and a back with no front before it is flagged.
- Identify, beside the card's name in Edit (Shift+I, and in the strip's menu): reads the number of the photo open and looks it up again, asking you to pick when it fits several cards; with several photos selected in the strip it reads them all in the background. The magnifier still searches by name (I).

## 3.7.12 · Quick prices, and a Market page that keeps up · 22 Oct 2026

- Price fields: the first key you type after clicking in writes over the whole price, whatever the click left selected, and the arrows and Up and Down move a whole dollar everywhere (the Market's price boxes moved ten cents). The big Edit price shows its selection in lime.
- Quick prices under the Edit price, and in the phone's price sheet and listing editor: the market price (TCGplayer's market, else eBay's median asking price), 10% over it, 25% over it, and up to the next whole dollar.
- Market: a Position column with a coloured pill per card (Over 47%, Under 22%, In market, inside your alert threshold), and All, Over, Under and In market filters in place of the title that had shrunk to a stray character; 40 cards a page.
- Price alerts go the moment you change a price, not when eBay's data next arrives; Clear all puts every alert away; drag an alert right to open the listing in Store, or left to dismiss it, and Listing opens it in Store too. Alerts put away here or on the phone stay away until that card's market price changes.

## 3.7.11 · A welcome line and the store's policies in every description · 22 Oct 2026

- Every listing description opens with a line from you under the title, about real studio photos of the exact card rather than TCGplayer stock, and closes with the store's policies: same-day handling before 2 PM Central, how cards are packed, no cancellations, no returns, questions welcome, and eBay's Money Back Guarantee. Both are set at the top of listing.py.

## 3.7.10 · Debug and clean-up round, the 3D moves as a tray · 22 Oct 2026

- The 3D view's moves on the Mac sit in a tray of line icons with a word under each, as on the phone: Front, Back, Flip, Spin, Sway, Turn (the turntable, lime while it runs), Enter, Exit, Camera and Centre, the last four opening their menus as before.
- Detect again from the phone, when it failed, raised an error of its own instead of saying why, since the error it meant to show was gone by the time the message was sent.
- Thumbnails on the phone are encoded by the phone server itself rather than by the window, which is busy while a batch develops and let them time out into broken images.
- The Store's listing filters size to a short label, so the Listings view fits a laptop window again (it had grown to 1,204 points).
- Unused imports and a stray f-string removed; the full test suite passes.

## 3.7.9 · No freeze after a long export, the List a page at a time · 22 Oct 2026

- The end of Export all rewrote the hero and listing files for every card in the session, on the window's own thread, which froze the app for minutes with the page change caught half way; now only the cards in that batch are written, one at a time between redraws, and heroes are made in the background.
- A page change's fading picture of the old page is removed within a second whatever happens, so it can never stay laid over the new page.
- The List shows 25 cards a page with Previous and Next; a new filter or search starts at page one, and All ticks every page of what the filter shows.

## 3.7.8 · The Mac's Store overview on the phone · 21 Oct 2026

- The phone's Store overview carries the Mac's modules, built from the console's own tiles, rows and chart card: each tile gets its figure underneath (sales and average, shipped or waiting, the value listed, watchers and on how many listings), Watchers replaces the Offers tile since offers have their own section, and below the actions come the sales trend (daily for 60 days or weekly for 12, read by touching a bar), eBay's traffic for 30 days with each figure's change and its last 14 days, where views came from, and the most watched and just listed listings, each opening its editor.

## 3.7.7 · Next up set by hand, a steady fan · 21 Oct 2026

- Next up in Shoot has Front and Back buttons, so the next shot can be switched by hand: Back joins the latest front still without one, Front starts a new card, and on the phone a tap on the Next up label does the same.
- The fan of cards no longer jumps between two layer orders as it sways: the sway turned each card and its place separately, so the cards stopped lying parallel and whichever end of the hand was nearer leapt to the top; the hand now turns as one, and its cards are drawn in their own order.

## 3.7.6 · Back thumbnails fill their frame · 21 Oct 2026

- On the phone, the small back picture on each Review card shared its class name with the page's back button, whose padding squeezed the picture into a strip with bars above and below; it now fills its card-shaped frame.
- The two sides on the phone no longer depend on the app-height measurement, which a browser tab reported as a percentage and which shrank the side to a thumbnail there.

## 3.7.5 · Older corners found again, card-shaped sides on the phone · 21 Oct 2026

- A restored session kept the corners the previous detector had found, so 3.7.4's better detection never reached photos already in the batch, and their filmstrip and phone thumbnails, cut from those corners, stayed wrong; corners you never touched, on photos not yet exported, are now found again when the session comes back, while corners you set by hand and exported photos stay exactly as they were.
- On the phone, both sides of a card show in the same card-shaped box, rounded as the card itself is (3.2 mm on 63 by 88), so the back is no longer a shorter strip than the front and no mat shows at the corners.

## 3.7.4 · Card backs found by their outer edge, nudges kept · 21 Oct 2026

- Detection on a black mat now finds a card back by its outer edge, since a navy border on black is nearly invisible to brightness, so the app used to lock onto the light inner frame, the logo lettering, or a skewed quad stitched between them; the card's colour silhouette is now traced on a 2000 px copy with its four sides fitted to the straight runs, rounded corners left out, and it wins unless the card sits in a sleeve.
- Only card-shaped, square-cornered outlines compete among the brightness edges, so small sharp letters no longer outrank the card.
- The background check weighs brightness the way the colour map does, so a lens's darker left edge no longer reads as a busy mat and switches the silhouette off.
- Corners moved with the arrow keys or in shape mode now count as yours, which they did not before, so a detection still running in the background could put the found corners back after an export.
- Photos compare by identity, which stops a rare error after clearing the filmstrip mid-export.

## 3.7.3 · Review rows stay inside their card · 21 Oct 2026

- On the phone's Review, a card's status and its Publish or Upload button no longer run past the card's right edge: the row wraps the button under the status when both do not fit. The back tucked into a card's corner now comes from the back photo's own small thumbnail, the one the filmstrip shows, so it loads at once; it had asked the Mac for the full straightened back of every card together, which timed out and left grey blocks. Corners on that page opens the side you are looking at, the back included. Both sides, opened large, show a spinner while the Mac prepares them and say so plainly when a side has no photo.

## 3.7.2 · The slab label is white again · 21 Oct 2026

- The slab's label is back to white stock with dark type; the clear label window from 3.7.1 stays.

## 3.7.1 · A red slab label, a clear window · 21 Oct 2026

- The 3D slab's label is deep red with white type and rules, front and back.
- The label's window is clear plastic: the frosting stopped only on the moulded face, so the flat inner sheet of the other half was still frosted behind it and showed grey through the window. Both halves are now clear over both windows, the label's and the card's.

## 3.7.0 · Phone: the whole frame, both sides, publishing, readable errors · 21 Oct 2026

- Shoot on the phone: the live view takes the camera frame's own shape, turned as the Mac's live view is turned, at the full width of the phone, so the whole card always fits and it is as large as the screen allows. The shutter, AF and Batch sit on the live view itself, and exposure folds into one line (f/11 · 1/6 · ISO 64) that opens into the three pickers and remembers whether you left it open.
- Both sides of every card in Review: the row shows the front with the back tucked in its corner, and tapping it opens both sides large, Front and Back, tap to zoom where you tap and drag to look around, with Corners and Condition report from there.
- Publishing from the phone: a card in Review that is up on eBay unpublished has Publish, and a card that is ready has Upload (it goes up unpublished, to check first). Both ask you to confirm on the phone and run on the Mac as List does.
- Status on a card stays on one line: a failure shows as Failed with an arrow, and tapping it shows eBay's full reason in a sheet instead of spilling over the row. Long progress like Uploading photo 6 of 10 is cut to fit. Setting a price under $0.99 on the phone is stopped there, with eBay's minimum named.

## 3.6.2 · Phone 3D: real corners, motions that flow · 21 Oct 2026

- The phone's 3D card has the same corners as the Mac's 3D view and the photos: true quarter circles of 3.2 mm, where it had a smaller, flatter curve.
- Motions flow into each other. A motion starts from wherever the card is drawn at that moment, even halfway through another, so tapping Spin during Showcase changes course instead of jumping back to rest first; when a motion ends the card eases back to rest; and a touch, Flip or Centre takes over from the current pose. Shine's light now leaves from and returns to where it rests.

## 3.6.1 · Phone: tab bar on the bottom edge, swipeable reprice suggestions · 21 Oct 2026

- Opened from the home screen, iOS can lay fixed things out against a viewport that stops short of the bottom of the screen, which is why the tab bar kept floating well above the edge whatever its padding. The console now sizes itself to the screen's own height from the top when it runs from the home screen, so the tab bar, sheets, the listing editor and shot review all reach the bottom edge.
- Market reprice suggestions on Overview: swipe left to dismiss one, swipe right to open its live listing in the editor, or Clear all. A dismissed suggestion stays away until the market's suggested price for that card changes, and the Mac remembers it, so it stays dismissed on every phone.

## 3.6.0 · Light mode on the phone · 21 Oct 2026

- Light mode for the phone console, in the gear's This phone sheet under Appearance: Dark, Light, or Match the iPhone (which follows the iPhone as it switches). Every surface, line, text colour, icon and button changes with it, the 3D stage's backdrop and the motion tray included, and the lime accent darkens to an olive wherever it is text or a line, so it stays readable on white. The iPhone's own status bar follows the next time the console opens from the home screen.
- The tab bar now reaches the bottom edge as one solid surface, so the band of a different shade under it is gone, and it sits lower.

## 3.5.2 · Phone: no stray lines, the motion tray fits · 21 Oct 2026

- The hairlines across the top and bottom of the Shoot tab's live view are gone: Safari draws a frame round an image that has no picture yet, and the live view's image is now hidden until a frame arrives.
- The 3D motion tray fits the stage when it is not full screen (smaller icons, no gaps), and the stage shows nothing until you pick a card instead of a blank grey card.

## 3.5.1 · Phone: foil, condition reports, cleaner 3D · 21 Oct 2026

- The 3D card on the phone has no floor shadow (with no floor, it looked like a glitch), a tighter corner so the border's printed lines are not clipped, and a Foil switch in the motion tray: the desktop's foil reflection, as a rainbow sheen that shifts as the card turns, remembered between visits.
- Condition reports from the phone: each card in Review has Condition report, which the Mac measures and draws as on the desktop and shows on the phone, with Add to listing photos. It needs the one-time calibration in Reports on the Mac.
- The live view on the Shoot tab is shorter, so the shutter and its controls fit above the tab bar.

## 3.5.0 · 3D on the phone: motions, recording, full screen; checks kept for good · 21 Oct 2026

- The phone's 3D card: the back is no longer mirrored, and the white flashes are gone (the card's edge piece drew its own faces exactly under the photos and flickered through them). Dragging is half as quick, a hard flick turns gently, and the card eases after your finger instead of snapping to it.
- A motion tray of icons along the bottom of the 3D stage: Tilt, Spin, Showcase, Reveal, Shine, Flip and Centre.
- Full screen: the corner icon hides the card tray, the tab bar and the top bar, and gives the stage the whole screen.
- Record: records the 3D card and its backdrop only, never the buttons over it, motions included. When you stop, save or share the video to Photos or Files, or send it to the Mac, where it lands in Videos.
- Price checks are kept for good, with their picture, what the card was read as, the candidates, the one you picked and its price that day. They live in ~/Library/Application Support/CardCrop/scans, beside the session, sales ledger, market history and settings, outside the app, so rebuilding or updating CardCrop never touches them. The Check tab lists them, 20 a page; open one to see it again or tap a candidate to price it again today, or remove it.

## 3.4.0 · Quieter phone, filters, insights, bulk prices · 21 Oct 2026

- The phone console is set in small, light type: body 14, secondary lines 12, titles 20 at a light weight, and labels in small spaced capitals. Fields stay at 16, the size below which iOS zooms the page when you type.
- The 3D card on the phone showed a blank face because its pictures were sent as JPEGs straight from 16-bit RAW pictures, or from the floating-point pictures tone edits make, which come out black or not at all. They are now converted to 8-bit first. Failed picture requests are no longer kept by the phone for ten minutes, and the 3D picker lists every card of the session, live ones included.
- Refresh on the phone reads eBay again on the Mac too, so both show the same store; pulling down at the top of any tab does the same.
- Filters for live listings, on the Mac and the phone: price range, time left, how long a listing has been up, and watched or not. Rows on the phone show the time left.
- Review on the phone follows List on the Mac: a card that is live or sold leaves Review, with a line saying how many have.
- Sales on the phone show pictures: your own exported front when CardCrop listed the card, else eBay's photo, fetched by the Mac.
- Five more: a 14-day sales line with the week against the week before on Overview; the market scan's reprice suggestions on Overview with one-tap Match; changing the prices of many listings at once by a percentage or an amount, on the phone (Select > Price) and the Mac (tick, then Prices…), never below $0.99; one search across this session's cards, live listings and sales from the magnifier at the top; and pull to refresh.

## 3.3.3 · Smaller type, the 3D card shows its front · 21 Oct 2026

- All type on the phone console is about a step smaller: body text 16, secondary lines 14, labels 13 and buttons 14, so sheets such as This phone no longer crowd their buttons.
- The 3D card on the phone always settles on its front. It arrived with a free spin that could stop on the back, and a card whose back CardCrop has no photo of then showed a blank grey face; it now turns to its front, a side with no photo says so on the card, and the phone tells you which side is missing.
- Price check keeps its finder at full size; only the note inside it is small.

## 3.3.2 · Phone fixes from the first look on an iPhone · 21 Oct 2026

- Live listings on the phone were laid out wrongly on the iPhone itself (Safari arranges a grid inside a button differently from the desktop browsers they were checked in). The rows are rebuilt, and each one now carries its own price and quantity fields: change either, tap Save, and it goes straight to eBay; tap the listing itself for every other field.
- The live view on the phone is portrait, like a card, and follows the turn you set on the Mac's live view, so a card shot sideways stands upright.
- The tab bar sits closer to the bottom edge, the Price check heading is a small label so the finder and its buttons fit above the tab bar, and the console asks to stay in portrait.

## 3.3.1 · The phone's certificate installs · 21 Oct 2026

- The setup page now hands the iPhone a configuration profile instead of a bare certificate. Safari had been saving the certificate to Files as an ordinary download, so it never reached Settings and no CardCrop entry appeared under VPN & Device Management. The profile goes to Settings as Profile Downloaded, ready to install, and the setup page now says to use Safari, since other browsers cannot install profiles.

## 3.3.0 · Live listings on the phone, room to breathe · 21 Oct 2026

- The phone console is calmer and more spacious: wider margins, more room between sections than inside them, one corner radius throughout, hairlines in place of boxes, and section labels that carry the hierarchy so the surfaces can stay quiet.
- Store on the phone has three views, Overview (what needs you: offers, sales to ship, uploads to publish), Live and Sales. Live lists your live listings 20 at a time with the Mac's own search, sort and store category filter, and pages through them, so a store of thousands opens as quickly as one of twenty.
- Every listing edit from the Mac is on the phone: title with its 80-character count, price, quantity, condition (kept for graded cards), offers with auto-accept and auto-decline, shipping policy with its local pickup, both store categories, a 360° video made by the Mac or one attached from the phone, a condition report, Open on eBay and End. Select several listings to move them into a store category together. Changes are checked the way the Mac checks them before anything reaches eBay.
- Every photo edit from the Mac is on the phone too: in shot review, Edit sets the card's name, identifies it by name or number against the photo, turns it left or right, swaps front and back, and holds the tone controls (exposure, contrast, highlights, shadows, saturation, warmth, sharpen, lens detail, presets and Reset), which apply to the whole session as they do on the Mac.
- The Mac's Store > Listings now shows 50 listings a page with Previous and Next, instead of building a row for every listing at once. Searching, sorting or picking a category starts again at page one, and Select all still ticks every listing that matches, across all pages.

## 3.2.0 · Phone console, second round · 21 Oct 2026

- Shot review on the phone: every shot from the Mac's camera lands in a strip under the shutter, and opening one shows the photo turned the way it was framed with its four corners to drag, pinch to zoom, double-tap to zoom on a corner, and a magnifier above your thumb while you drag, so the corner hidden under your finger is the one you can see best. Save writes the corners to the Mac as set by hand, Find edges looks again, Straightened shows the card as it will export, and Retake takes the shot off the session so the next one replaces it as the same front or back. Switch on Check each shot and every new shot opens on its own.
- Price check: a new Check tab uses the phone's own camera, or a photo from the library, and sends the picture to the Mac, which straightens it, reads it and prices it with the same sources as List: your own sales, PriceCharting, TCGplayer and eBay's asks. Tap another candidate to price that one instead, or type a name when the number cannot be read.
- Selling from the phone: buyers' offers with Accept, Counter and Decline; sales waiting to ship with Mark shipped, a tracking number and the carrier worked out from the number; and uploads that are not live yet with Publish.
- Notifications: from the gear on the phone, choose to hear when a card sells, a buyer makes an offer, the market scan finds prices to check or an export finishes. They are Web Push messages that CardCrop encrypts for each phone and signs itself, so they need iOS 16.4 or later, the console opened from the home screen, and CardCrop running on the Mac.
- Away from home: when Tailscale runs on the Mac, its address and name join the certificate, and Settings > Phone can hand the phone that address, which works anywhere the phone and the Mac are both signed in to Tailscale. The default address on home Wi-Fi is now the Mac's Bonjour name rather than its number, so a new address from the router no longer breaks the home-screen app. Each address pairs on its own, since the phone keeps one pairing per address.
- Sales read from eBay now keep their order numbers, which marking shipped needs: refresh the store once after updating.

## 3.1.0 · Phone console · 21 Oct 2026

- CardCrop now runs a small console for your iPhone on the same Wi-Fi, switched on in Settings > Phone, where a QR code and a six-digit code pair the phone once and a hash of its token is all the Mac keeps, so a lost phone is removed with Forget and is shut out at once.
- Shoot from the phone with the live view streamed at up to 8 frames a second, the shutter, autofocus, aperture, shutter speed and ISO as native iOS pickers, and the batch switch, while the Mac stays the camera's host.
- Review from the phone: pick the right card for photos the identifier was unsure of, set the grade and the price for every card in the session, and export the ready ones.
- Store from the phone: sales, cards to ship, active listings with a search, a new price sent straight to eBay, and recent sales.
- 3D on the phone: any named card with its real front and back, turned by a finger with momentum, flipped with a double tap, and tilted by the phone's own motion sensors with the light sliding across the surface.
- It is a web app rather than an App Store app, served by CardCrop itself over HTTPS with its own certificate authority, which the phone trusts once through a profile from the setup page; that is what iOS requires before a page may read the gyro. Add it to the home screen and it opens full screen like an app.
- Needs two new packages, segno and cryptography, which the build script installs. The first time it starts, macOS asks whether CardCrop may accept incoming connections: allow it.

## 3.0.11 · Square sleeve corners · 21 Oct 2026

- **Sleeves have hard corners again.** The fitted sleeve's corners are now cut square, as real sleeves are (a 0.3 mm radius, so the film's corner still catches a little light), instead of rounded like the card.

## 3.0.10 · A PSA slab · 21 Oct 2026

- **The slab is built to PSA's published size:** 80 x 135 mm and 9.05 mm deep, with a rounded rim. A label window sits at the top, over a line that separates it from the card's space below. The card's space is one open window with no well of its own, and four clear bars hold the card in place around PSA's 64.5 x 90 mm space. The label window is drawn 64 x 27 mm (PSA's is 68 x 30) so its bevel clears the rim's slope, and the label sits inside it with a margin, its lines set a little tighter.
- **Frosted, not green.** The slab's plastic is neutral now, with no green-grey acrylic tint. It has a frosted-glass look everywhere except the card's and the label's windows, which stay clear.
- **The rim's step is rounded.** It follows the slab's corners and steps down to the face over a soft slope, instead of a hard line with square corners.
- **Both sides moulded, no doubled bevel.** Each half of the slab moulds only its outside face, so the back of the slab looks right again and no second bevel shows round the label.
- **A fitted sleeve.** The sleeve is now a fitted one, 64 x 89 mm with rounded corners, so a sleeved card fits inside the slab's bars with nothing overlapping. The card still rests on the top loader's bottom rail in its fitted sleeve.
- **Smaller tooltips:** 3 pt smaller than the app's text, with tighter padding.

## 3.0.9 · One bevel round the label · 21 Oct 2026

- **The extra bevel above the slab label is gone.** Since the slab became two halves, the back half drew the moulded rim and the label and card windows as well as the front half, so a second, slightly offset bevel showed round the label. Those belong to the front half's face, so only the front half draws them now.

## 3.0.8 · The card rests on the rail · 21 Oct 2026

- **In a top loader the card now sits on the bottom rail, not in it.** The welded bottom rail is closed plastic, but the sleeved card sat 1.7 mm down into it. The loader now sits 1.75 mm lower around the card, so the sleeve's bottom edge rests right on the rail's seam line, and the loading animation ends there too. A new check measures it.

## 3.0.7 · A smooth close, and real top loader rails · 21 Oct 2026

- **No jump at the end of slabbing.** Three things happened in its last second, all fixed:
  - The front half's press went half a millimetre past closed, so the sleeved card showed through it and then slipped back. It now settles onto the back without ever passing closed.
  - The halves met exactly at the middle of the card, so their inner faces cut through it. Each half now stops a hair short, leaving a pocket for the sleeved card; together they are still exactly the slab's depth.
  - When the move ended, the halves were swapped for the one-piece slab, which places its label and inner frame and shades its window a little differently. A slab at rest is now drawn exactly as the move ends, with the halves' label and inner frame where the one-piece slab has them.
  Measured frame by frame, the last second and the moment it ends now change no more than a slab standing still.
- **Top loaders have their welded rails.** Like a real one, a top loader is now welded down the left, right and bottom edges. Those edges have a band of thicker, slightly blue plastic (about 2.4 mm at the sides and 2.7 at the bottom) with a fine seam line on its inner side, and a hairline seam just inside the open top. The rails are thicker plastic, so they darken a little more at an angle.

## 3.0.6 · A sleeved slab, and a camera that stays put · 21 Oct 2026

- **Slabbed cards are sleeved.** The card goes into the slab in its penny sleeve, and stays sleeved in the slab at rest. From a bare card the sleeve goes on first and then the slab closes round it. From Sleeve it goes straight into the slab. From Top loader only the loader comes off, then the slab. Leaving the slab for Sleeve just opens the slab, and leaving it for None opens the slab and then takes the sleeve off.
- **Both slab halves rise from below.** The back half rises from below the frame and comes in behind the card; then the front half, label and all, rises from below in front of the card and closes onto the back. Both start well out of shot, so nothing appears out of nowhere.
- **No more pulling out for the top loader.** Sleeve and Top loader now keep the card's own shot, with no zoom in or out. The camera only drifts a few millimetres to centre on the loader. Only the slab, which is taller than the shot, eases the camera back, smoothly over the move.
- **No jump when a move starts.** A move's first frame used to be drawn a moment late, so for one frame the card showed bare in the card-only shot before the holders came back; picking Slab showed it most. The first frame now goes up at once.
- New checks: the card stays sleeved through the slab move, both halves start out of shot, sleeve and top loader keep the card's shot, and the routes between holders are as above.

## 3.0.5 · Slabbing, steady framing, corners that stay put · 21 Oct 2026

- **Slab plays too.** Picking Slab in 3D now assembles one around the card. The back half rises from below and comes up behind the card, which settles into its clear inner frame. Then the front half, label and all, comes in from in front, closes onto the back and presses home with a small give where the halves meet. Picking None plays it backwards. Going between Slab and Sleeve or Top loader plays one move after the other: out of the first holder, then into the next. "Into a slab" and "Out of the slab" are also in Animate's camera moves, for videos.
- **No more camera jump with Sleeve and Top loader.** A holder at rest is framed to fit the holder, but a move was framed on the card alone, so the camera leapt in at the start and back out at the end (by a third, for the top loader). Now the framing eases from the holder you start in to the one you end in over the whole move, and each end matches the resting shot exactly. The card also turns from wherever you left it, rather than snapping to the move's angle.
- **Hand-set corners no longer snap back after export.** A new photo's edges are found in the background, and also straight away when you open it. When the background search finished late (a busy pool while tethered), it wrote its corners over the ones you had fixed and marked the photo unedited, so after export it jumped back to the detected outline; the exported files did have your corners. Now detection never replaces corners you set by hand. Detect again still resets them on purpose.
- New checks: corners survive a late detection before and after export; every holder change plays and lands, eases its framing between the resting shots, and the slab's halves close exactly where the whole slab sits.

## 3.0.4 · Smaller upload chips · 21 Oct 2026

- **Upload chips are chip-sized.** In List the chip stretched to the full height of the row, and its spinning mark grew with it. It is now a fixed 26 pt chip with a 12 pt mark, its spinner turns smoothly (30 times a second, not 10), and in a narrow column it drops the clock before it cuts off the words ("Publishing…" rather than "Pu…").

## 3.0.3 · The stack flips cleanly · 21 Oct 2026

- **Flip through the stack works again, in holders too.** The front card's old path lifted it only part way and turned it while it was still level with the stack, so it would have cut through the card behind. A safety pass shoved the whole stack back to make room, then let it spring forward again, which is the glitching you saw, and in top loaders the card looked stuck on top. Now the front card rises clear, turns over while it travels above the stack (its lowest point stays above the top of the stack at every angle), then drops straight down into the back slot while the rest step forward. Nothing is pushed out of its way any more, and the framing leaves a little more room above for the rise. A new check runs this bare, in top loaders and in slabs, with 2, 3 and 6 cards: no card passes through another, nothing jumps between frames, and the flipped card always lands at the back.

## 3.0.2 · Holders that sleeve themselves · 21 Oct 2026

- **Picking a holder plays it.** In 3D, choosing Sleeve or Top loader now plays the sleeving instead of jumping. None to Sleeve slides the card into the sleeve, and None to Top loader sleeves it and then loads it. Sleeve to Top loader plays just the loading, since the card is already sleeved, and going back plays it in reverse. Picking a new holder mid-move starts from where the move was heading. Slab still appears at once, and with Motion off (Settings > App) every holder jumps as before.
- **The bare top loader is gone.** Top loader now means sleeved in a top loader (it was "Sleeve + loader"). A card you had set to the bare top loader opens in the sleeve and top loader.

## 3.0.1 · Sharper photos · 21 Oct 2026

What was making them soft: two of your shots from tonight (CC00025 and CC00026: a6700, 30mm macro, f/8, ISO 100, 1/60) put the card at about 5,200 by 3,700 pixels, more than three times what eBay shows, so it is not a lack of resolution. But the card's brightest print only reaches 31% of the sensor's range, about 3 stops under. Brightening that afterwards brings up the sensor's grain with it, and grain reads as softness.

- **Dark captures are flagged as they land.** Each tethered shot is measured, and if it is a stop or more under you get a warning saying how far, with a button that sets the shutter speed that fixes it (1/60 at 3 stops under becomes about 1/8). On a tripod with the camera fired from CardCrop, a slow shutter is fine, and ISO stays at 100.
- **Lens detail** (Settings > Lens, on at 50). At export, a Richardson-Lucy deconvolution undoes the slight blur the lens, the aperture and the sensor add. Lettering and print edges come back crisp, while flat areas and grain are left alone, because the photo's own noise level decides where it applies. On CC00025 it sharpened the text with almost no change to the grain. It recovers detail that was captured and paints in none, which is why there is no AI upscaling: a buyer judges condition from these photos, and invented texture can hide or fake wear.
- **Photos to eBay are sized and sharpened for how eBay shows them** (Settings > App > Prices). eBay recommends 1600 px and zooms on that, so by default photos now go up at 1600 px with a fine sharpening pass at that size, instead of 4000 px that eBay shrinks with its own softer resize. 2400 and 4000 are still there.
- The glow on Export and next and on Ready is now a hairline, and no longer gets cut off.
- The Store listing editor's buttons are one row: Video, File…, Report, eBay ↗, End.

## 3.0.0 · Shoot a batch, review only what needs you · 21 Oct 2026

3.0 changes how a batch goes. Shoot every front and back without stopping, and CardCrop reads, names and prices each card behind the camera. Press E, and Ready exports everything it is sure of in one go, so what is left is only the cards that need you. Rounds 2.48 to 2.52 built it; this round adds the video effects and makes it 3.0.

**New in this round: video backdrops and reveals.** The 3D export has two new rows. Backdrop offers Still plus three moving backdrops drawn on the graphics card for every frame and tinted by your background colour: Rings (concentric ripples with their colour channels a hair apart, after the 21st.dev shader animation), Lines (falling streaks of colour in lanes, after shader lines) and Aurora (slow folding colour). Reveal draws over the first moments of the video: Ring reveal (the rings fill the frame and open from the centre onto the card), Holo sweep (a band of foil colour crossing the frame) or Lock-on (crosshairs and corner brackets that close in on the card, after the React Bits crosshair). The reel uses whatever reveal you last chose. A moving backdrop also shows live in the 3D view. Neither is used with ProRes 4444, which stays transparent.

**What 3.0 is, from 2.47:**
- **Groundwork (2.48).** app.py went from 15,000 lines to 1,400, split into parts, and a set of checks (`python tests/run.py`, now 15 of them) runs before every round.
- **Crash-safe batches (2.49).** Pairs stay linked and a waiting front keeps waiting for its back through a crash, and every capture is saved the moment it lands.
- **Motion (2.49).** Pages dissolve, the rail marker glides, buttons ripple, toasts rise, new shots slide into the filmstrip and the shutter flashes. Store shows loading states. All of it can be turned off in Settings > App.
- **Background reading and Ready (2.50).** Fronts are read while you keep shooting, backs take their names, prices are fetched, and Edit opens first on what needs you.
- **Prices from sales (2.51).** Your own sales of the card come first, then PriceCharting (with a token), then TCGplayer, and eBay's current asks only when they are believable. Unpriced cards fill in. Your sales are kept beyond eBay's 60 days.
- **Sold inventory (2.51).** Sold cards say Sold, have their own tab in List, and can be listed again as another copy.
- **Status at a glance (2.52).** Status marks, the reading HUD in Shoot, upload chips, glowing primary actions, real checkbox ticks, sortable listing columns and sales grouped by day.

## 2.52.0 · Status you can read at a glance · 21 Oct 2026

Native versions of the React Bits and shadcn pieces you sent, redrawn in Qt rather than embedded.

- **Status marks** (after Status Mark). Every filmstrip tile and List row now has a small mark instead of a dot: a dashed ring while waiting, a spinning arc while edges are found or the card is read, a check that draws itself when exported or listed, and a cross when it fails. A card that needs you has an amber ring.
- **Reading HUD in Shoot** (after Lattice Loader and Thought Line). While the background pipeline reads cards, the top of the live view shows a 3 by 3 lattice whose cells light in a wave, beside "Reading 2 cards…" with a light passing across it and a running clock. When it is done the lattice settles into a check (or a cross if any card needs picking), the line folds to "Read 6 cards, 1 to pick" with the time, and it fades a few seconds later. Click it to see each card it read.
- **Upload chips** (after Call Chip). An upload's current step shows as a chip whose wash fills as the photos go up (or creeps toward done on steps that do not count), with its clock running, then a check when it lands. A failed row gives a short shake. Market's price scan uses the same chip.
- **Glowing primary actions** (after Border Glow). Export and next, and Ready, have a soft lime glow that breathes and gathers on the side your pointer is nearest.
- **Checkboxes have a real tick** now, not just a filled square (after the shadcn checkbox).
- **Store listings sort by column** (after the shadcn data table). Click Listing, Qty or Price to sort, and click again to reverse the order; an arrow shows which way.
- **Store sales are grouped by day**, with a heading between days (Today, Yesterday, Mon 19 Oct), after the shadcn marker.

## 2.51.0 · Prices from sales, and cards that sold · 21 Oct 2026

- **Prices start from what cards sold for.** The suggestion now starts from a sold figure: your own sales of that exact card first, then PriceCharting's ungraded value if you add a token, then TCGplayer's market price (all three come from completed sales). It drops to the lower quarter of eBay's current asks only when those are cheaper and not under 70% of the sold figure, since asks that low are usually other printings or bait. The line under the price and its tooltip show your sales and PriceCharting beside eBay and TCGplayer. eBay's own sold-items API (Marketplace Insights) is limited to approved partners, so it is not used.
- **Unpriced cards are priced for you.** When a suggestion arrives for a card you have not priced, it fills in, so a batch from the background pipeline reaches List already priced. A price you set is never changed, nor is the price of a card already on eBay. You can turn this off in Settings > App > Prices, where the optional PriceCharting token also goes.
- **Your sales are kept for good.** eBay only returns 60 days of sales, so every Store refresh now adds them to a ledger on disk. Store's sales list and its CSV export show every sale CardCrop has seen, and pricing reads your own history from the ledger.
- **Sold cards say Sold.** A card that sold and has no copies left on eBay shows as Sold in the filmstrip and in List, which has a new Sold tab (sold cards are out of All). Before, a sold card stayed "Live" forever and could not be listed again. Now if you have another copy, tick it in List and Upload, confirm "List again?", and it goes up with the new photos. Sold cards are never uploaded again automatically.

## 2.50.0 · Cards are read while you shoot · 21 Oct 2026

- **Background reading.** In pair or batch shooting, each front is straightened, its number read and the card looked up as soon as its edges are found, on one low-priority thread behind the camera. A sure match names the card and its back, and fetches its price for List, all before you leave Shoot. The filmstrip says "Reading the card…" meanwhile. Backs are never read; they take their front's name.
- **Ready.** A new Ready button beside All exports every card CardCrop is sure of in one go: each side found with strong edges (or set by hand) and the card identified. Whatever is left is what needs you.
- **Edit opens what needs you first.** Coming in from a batch, Edit opens the first card that needs a look, not just the first one shot. A front whose number fits several cards is marked ? with "Pick the card" (press I to choose), and Next ⚠ stops on it too.
- A reading cut short by a crash or a quit runs again after a restart.

## 2.49.0 · Motion, and batches that survive a crash · 21 Oct 2026

- **Pages dissolve into each other.** Switching stages fades the old page out as it lifts a few points, instead of cutting (the 3D stage still cuts, since a GL view cannot be photographed).
- **The rail marker glides.** The highlight behind the current stage slides to the one you pick, with a slight overshoot, so your eye follows where you went.
- **Every button answers a press.** A soft ripple spreads from where you clicked, on every button in the app, white on dark buttons and in dark mode.
- **Toasts rise and fade** in, and fade out when they time out or you dismiss them, instead of popping.
- **The filmstrip eases new shots in.** A new tile slides in from the left, and its photo grows into its grey slot when the thumbnail lands.
- **Shutter flash.** A quick white flash on the live view the moment a capture lands.
- **Loading states.** Store shows a lime bar sweeping along its top while it fetches, and on a first load (nothing cached yet) grey placeholder rows with a light sweeping across them, which only appear if the fetch takes longer than a beat. List and Market rows cascade in from the top; Tracking's big figures count up to their new values.
- **Motion can be turned off** in Settings > App, which makes every change instant again.
- **Batch shooting survives a crash.** The session now remembers which back belongs to which front, and a front still waiting for its back, so after a crash or a force quit you pick up on the right side of the right card. Every capture is written to disk the moment it lands, and the rest saves every second (only when something changed) instead of every three.

## 2.48.0 · The groundwork for 3.0 · 21 Oct 2026

Nothing you will notice on screen, and that is the point: this round is the base the 3.0 work stands on.

- **app.py is split up.** It had reached 15,000 lines, which is why fixing one thing kept breaking another. The window is now 1,400 lines, with its work in six parts (main_shoot, main_queue, main_session, main_ebay, main_reports, main_export) and its pieces in eleven more (ui_base for the theme and icons, ui_widgets, ui_tasks, ui_editor, ui_live, ui_dialogs, ui_store, ui_list, ui_market, ui_reports, ui_viewer3d). The code moved as it was and none of it was rewritten, so the app should behave exactly as 2.47.0 did. The build script picks up the new files.
- **A set of checks runs before every round.** `python tests/run.py` opens the window offscreen with a private home folder (your settings and session are never touched) and runs nine checks: every stage opens and fits a 1440 screen, both themes and type sizes, pair and batch shooting, edge finding, the dark-shot retry, export, the store listings fill, the number reader, the session coming back after a quit, and every window method the code calls actually existing. Each round now has to pass all of them before it reaches you.

## 2.47.0 · Batch shooting · 21 Oct 2026

- **Batch: shoot every card, edit later.** A new Shoot option keeps you in live view the whole time: front, back, next front, next back. Next up counts the cards as you go (Card 3 · Back). Press E for Edit and it opens the first card still to do; Enter exports it and opens its back, which takes the front's name, and so on through the batch, back to live view only when all are done.
- **Uploads never slow the live view.** Uploading, publishing and carousel slides now run at low priority, so preparing photos for eBay gives way to the camera; and while you shoot tethered, good news goes to the status line rather than a toast over the live view (problems still show).
- **Centre lines on the card overlay.** The live overlay carries a yellow line across its middle each way, turning with it, to square the card up by.
- **Edges found after your edits too.** Edge detection works on the photo as shot (lens corrected); when it is unsure (a dark back on a dark mat), it now looks again with your tone edits on and keeps whichever finding is surer. On darkened test shots this took three weak findings (0.31 to 0.56) to 1.0, 0.6 and 1.0.
- **Store listings appear at once.** The list shows its first screenful straight away and adds the rest a batch at a time, each row fading up as it arrives, with grey placeholders until the photos come in. 587 listings now show in a tenth of a second instead of freezing the window for eight.

## 2.46.2 · Pick the game while shooting · 21 Oct 2026

- **Pokémon, Yu-Gi-Oh! or One Piece in Shoot.** The Shoot panel has the three games side by side; pick the one you are shooting and identifying reads each card's number the way that game prints it. It is the same choice as Usual game in Settings, and changing either changes both.

## 2.46.1 · Change an identified card's language · 21 Oct 2026

- **Language is editable.** Under an identified card's name in Edit, a language button (English ▾) changes the card's language, front and back together, keeping everything else it was identified as. The title and item specifics follow at once (Pancham 60/106 Flashfire Chinese Pokemon TCG Card), and a card already on eBay picks it up when it uploads again.

## 2.46.0 · Chimes · 21 Oct 2026

- **A ding for each step.** A light, high ding when a shot comes in from the camera, two rising notes when photos are exported, and a little four-note sparkle when cards go up to eBay or go live. They are soft bell tones made by CardCrop itself, quiet enough to work over, and play without slowing anything.
- **Off in Settings.** Settings has a Chimes tick box (on to begin with); ticking it plays the sparkle so you hear the volume.
- **Name searches keep to one language.** A name you type in Identify is looked up only in the language picked in its menu, so English, Japanese and Chinese cards are never mixed in one list. The menu opens on the card's own language when the photo has been read as another one. Reading the number off the photo still looks across languages and lets the picture decide.

## 2.45.0 · Chinese and Korean cards · 20 Oct 2026

- **Chinese cards are identified and searched.** Traditional Chinese (Taiwan and Hong Kong prints) and Simplified Chinese (mainland prints) come from the same free card database as English and Japanese, and so do Korean cards. Pick them in Identify's language menu, or let CardCrop find them.
- **The card's own language first.** Identifying reads the card's language off the photo (Chinese characters, kana or Hangul in its name) and looks in that language's cards first, then the one you chose, then English. A number that fits no card in its language is tried in Japanese, Chinese and Korean before giving up, so a Chinese card is found even when its language is not read.
- **One number, several languages: the photo decides.** A number like 068/98 is a card in English, Japanese and Chinese at once, so unless the photo's language is clear, every language is asked and the candidates are ranked by how closely their picture matches your photo (your Lugia EX scored 0.78 against 0.07 for the Japanese and Chinese cards with the same number). This makes identifying take a few seconds longer.
- **Type in English, find it in any language.** Searching charizard ex with Chinese chosen finds 噴火龍ex through its Pokédex number, as Japanese already did.
- **Listed in English.** Chinese and Korean cards get their English name from the Pokédex number (Charizard ex for 噴火龍ex), and CardCrop learns each species name as it meets it, for the cards that carry no Pokédex number. Titles and item specifics say Chinese or Korean, as Japanese cards say Japanese.

## 2.44.1 · Exports never wait in line · 20 Oct 2026

- **Export no longer sticks greyed out.** Exporting several photos ran in the same small pool of workers as identifying, thumbnails and eBay lookups, so when those were busy (reading every listing's store categories, say) the export waited behind them with its buttons greyed out. Exports now run on a line of their own and start at once, and the button counts them through: Exporting 1 of 2…

## 2.44.0 · Card numbers read far more often · 20 Oct 2026

- **Both corners, both ways up.** The number reader now reads the whole bottom strip, then each bottom corner on its own and larger (old sets print the number on the right, new ones on the left), light-on-dark too, and then the card turned round in case it was the wrong way up.
- **Noise is not taken for a number.** Every reading is checked against the set totals that exist, stray letters and digits stuck to the front are dropped (D067/072 reads 067/072, 556/62 reads 56/62), and a slash misread as a 7, 1 or l is recovered (9971147 reads 99/114). When the best reading matches no card, the next most likely ones are tried.
- On 44 of your own cards (32 exported modern cards and 12 vintage fronts from tonight's shots) it read 43, against 38 before, and still read all 12 vintage cards when they were upside down. The one it misses is a promo with no set total (SWSH055).
- **Edit does not start in the name field.** The keys stay on the photo, so I identifies straight away; click the name field to type a name.

## 2.43.0 · Live listings in a tab of their own · 20 Oct 2026

- **Live gets its own tab in List.** Cards already live on eBay leave All and On eBay and sit under Live, so the other tabs show only what is still being worked on.
- **On eBay** now means uploaded or drafted but not live yet, and a new **Uploaded** tab shows just the unpublished listings waiting for Publish.

## 2.42.0 · The card overlay, edited as you see it · 20 Oct 2026

- **Scales both ways with the camera turned.** The live card overlay was shaped in the sensor's orientation, so with the view turned (camera shooting vertical) it became a wide card that only grew sideways. It is now edited on screen as you see it: a portrait card that scales from any corner, keeping the card's shape.
- **Snaps to the centre.** Moving the overlay snaps it to the centre of the frame (and to either centre line on its own), with the centre lines shown while you move it, solid once it sits dead centre. Hold Shift to move freely. Turning it snaps square within a degree and a half.
- **Option-drag scales from the centre.** Drag a corner with Option held and the overlay grows or shrinks about its centre.

## 2.41.1 · A new card after live view is a new card · 20 Oct 2026

- **Nothing carries over into the next card.** After exporting several selected photos and going back to live view, the old photos stayed selected on the filmstrip, and the next shot could take the last card's name and open as its back, so Identify and Export acted on the old card. Going back to live view now clears the selection, a new shot opens on its own, and the front of each new pair always starts as an unnamed front.

## 2.41.0 · Shipping policies in the listing editor · 20 Oct 2026

- **Local pickup as eBay has it.** The listing editor reads local pickup straight from eBay (the shipping policy's setting, or a Pickup service on the policy or the listing) and shows it with what the policy offers: each service and its cost, pickup, and handling time.
- **Pick the shipping policy.** The Local pickup tick box is gone. In its place, a Shipping policy menu lists your business policies from Seller Hub, each marked when it includes local pickup, with its services on hover; pick one and Save to eBay moves the listing to it. Policies themselves, local pickup included, are still made in Seller Hub; the refresh button reads them again after you change them there.

## 2.40.2 · Local pickup saves · 20 Oct 2026

- **Local pickup turns on.** eBay refused the copy of your shipping policy with pickup added (LOCAL_PICKUP_ONLY_ERROR) because the copy had no ship-to region, which eBay reads as pickup only. The copy now ships to the US as yours does, with pickup as an extra, and never lists pickup as a shipping service of its own. If eBay still refuses, the message says which policy to make in Seller Hub, and CardCrop uses it from then on.

## 2.40.1 · Back to shooting after each card · 20 Oct 2026

- **Tethered, the next card is next.** With the camera connected, exporting a card's second side (front and back both out) goes straight back to live view, even when older photos on the filmstrip are still waiting. Exporting several selected photos at once does the same when it finishes.
- **Store's filter and sort menus show their whole label.** They keep the width of their text and the search field gives way instead.

## 2.40.0 · Reports in two steps · 20 Oct 2026

- **Make, then add.** Reports now take two steps. 1 Make reports makes one for each ticked card (or live listing) and keeps it to look over; nothing changes on a listing yet, and the card shows "Report made · not added yet". 2 Add to listings puts each made report up as the listing's last photo: into the card's listing photos (photo 12) for your cards, or live on eBay for listings. A single card's preview works the same way, and a made report waits for you between sessions.
- **No more boxes in report titles.** The report's typeface has no Greek letters or card symbols, so δ is written Delta, and ♀, ★ and the like are written out.
- **No page scroll for a few pixels.** The listing editor in Store and the traffic panel in Overview scroll on their own when the window is short, instead of pushing the whole page into a scroll; the report preview needs less height.
- **The step arrows read in dark mode.** They are drawn in the current theme's colours, so they show as arrows on dark grey rather than blank white tiles.
- **Export the photos you select.** With more than one photo selected on the filmstrip (Cmd- or Shift-click), the export button reads Export N selected and Enter exports just those, together, whether or not they were exported before.
- **The listing editor fits.** Its buttons sit in a two-column grid (Upload video… is now Video file…), and its menus shrink to fit.

## 2.39.4 · Every page fits a laptop window · 20 Oct 2026

- **Store Overview** no longer cuts off at the left: it needs about 820 points instead of 980. The buyer now sits under each sale's title rather than in its own column, the sales search shrinks, and the traffic figures take less room.
- **List** (1,010 to 770): Select Ready, All and None sit on their own row, the search shrinks and the columns are tighter.
- **Market** (990 to 800): the movers' columns are tighter and the alert settings take two rows.
- **Reports** (960 to 710): the report buttons sit on two rows and the search shrinks.

## 2.39.3 · Store fits the window · 20 Oct 2026

- **The listing editor is no longer cut off.** Store's Listings tab now needs about 850 points instead of 1,340: the search, category and sort fields and the counts shrink to fit, the editor's buttons sit on two rows, and the tab is sized by itself rather than by the wider Overview behind it.

## 2.39.2 · Titles eBay accepts · 20 Oct 2026

- **No refused symbols in titles.** eBay turns away titles and item specifics with symbols (error 25019). Titles, item specifics and live title edits now write ♀ and ♂ as F and M, ★ as Star, ◇ as Prism Star, fractions as 1/2, superscripts as plain letters, and drop ™, ®, hearts and other pictographs. Accented letters (Poké) and δ stay.
- **Stuck listings fix themselves.** Publishing an unpublished listing that eBay refused for this reason rewrites its title and item specifics and tries again, so Nidoran♀ goes up as Nidoran F without uploading it again.

## 2.39.1 · Every listing's categories · 20 Oct 2026

- **Categories read for every listing.** The seller list is now asked twice (listings ending in the next 119 days and listings started in the last 119), and any active listing still missing is read on its own, so listings in Other, Graded and the rest show and filter correctly.
- **No store category shows its count** in the filter.
- **The ▲▼ pair is exactly as tall as the field** beside it.

## 2.39.0 · Store categories in Store, arrows for quantity and price · 20 Oct 2026

- **Store categories on every listing.** Store reads each active listing's first and second store category from eBay and shows them under its title.
- **Filter by category.** A category menu above the active listings shows just one category's listings (a parent takes in its subcategories), or the ones in none, each with its count.
- **Change categories together.** Tick listings (Select all and Select none tick what the search and filter show), then Store categories ▾ puts them all in a first or a second category, live, keeping the other one.
- **Arrows, not scrolling.** Quantity and price in the listing rows have up and down arrows, and the Up and Down keys step them (price by 10¢); a run of steps is sent to eBay once it pauses. The scroll wheel no longer changes a price or a quantity anywhere; it only scrolls.
- **Upload video… sits in the live listing editor** (added in 2.38.0), for a video you already have.
- **The 3D card list reads in light mode.** Its drop-down is dark with light text, like the bar it opens from.

## 2.38.0 · Shoot both sides first, toned thumbnails, two store categories · 20 Oct 2026

- **Shoot both sides, then edit.** A new option in Shoot (on by default): after the front you stay in live view, shoot the back straight away, and only then does the front open to crop and identify. The back takes the front's card the moment the front is identified, and Enter after the front opens its back.
- **Corners light up when you grab them.** Holding a corner crosshair lifts the photo (stretched between its darkest and brightest tones, shadows opened), in the loupe too, so a dark border on a dark shot is easy to place; let go and the true photo is back.
- **Thumbnails show your edits.** The filmstrip and List tone their pictures with your edits as you move the sliders, and a photo's filmstrip picture is redrawn from the edges you set when you move on from it. The Instagram carousel dialog shows the slides with the edits on.
- **Two store categories.** Each card, the default for new listings, and a live listing in Store can have a first and a second eBay Store category; both are read from eBay, sent with uploads and drafts, and changed live.
- **Upload video… in Store.** A live listing can take a video you already have: the one rendered for it earlier is offered first, or pick any MP4 or MOV.
- **Video exports keep the backdrop photo.** The export dialog's Background now offers your backdrop photo (and picks it when one is set) instead of quietly switching back to the last colour.
- **Animate follows the card on screen.** Animate starts from the card in 3D, including one shown from a live listing; the saved animation reopens only if that card is in it. The card picker lists the card on screen and this batch first, and has Select all and Select none.
- **Floor reflections show only the near side.** A turned card reflects its back alone, with no face showing through it.
- **Sleeving is framed on the card.** The sleeve and top loader now wait off screen and slide in; they never move the camera.
- **Stacks hold their layers on any GPU.** The near plane now sits just in front of the nearest card, and cards are drawn far to near with each nearer card nudged forward in depth, so no card behind ever shows through one in front.
- **The animation editor fits a laptop.** Its toolbar is two rows, with shorter labels, so the window no longer grows wider than the screen.

## 2.37.1 · Air between stacked cards · 20 Oct 2026

- **No more bleed-through in stacks.** Cards behind the front card were showing through it, because the depth buffer could not tell layers a fraction of a millimetre apart. The view now asks for a 24-bit depth buffer, a group's near plane sits further out so that precision goes where the cards are, and stacked cards keep 1.2 mm of air between them, so every layer resolves and the stack's edge reads as separate cards when you turn it.

## 2.37.0 · Solid stacks, sleeving blocks, Blender export · 20 Oct 2026

- **Stacks are as deep as their cards.** Stacked cards now sit one real card thickness apart (or one holder's, when they are in holders), so a stack of ten is ten cards deep rather than a loose column, and turning a stack shows its true edge.
- **Cards are solid.** Where two cards overlap face to face and one tilts, flips or rises through the stack, the card behind is eased back just far enough to clear it, so a card rising up behind the front card passes behind it instead of cutting through it (the clipping you caught).
- **Shadows turn with the cards.** Each card's floor shadow and backdrop shadow take the shape it actually casts as it spins, narrowing to an edge when it is side on.
- **The back has a satin coat.** Card backs now catch a soft highlight and a little of the room, as printed stock does, instead of reading flat and dark.
- **Sleeves as blocks.** A new Sleeves menu: Sleeve it, Sleeve it then top load, Out of the top loader and sleeve, Out of the sleeve. Each acts on just the cards it is linked to, so one card can be sleeved while the rest of the stack moves.
- **Separate a card from a block.** Right-click a block (or use Separate every card in its properties) to give one card, or each card, its own copy: slide, stretch or restyle it alone while it keeps its place in the stack. Copies are marked ◆.
- **Keys and copies.** Cmd C, X, V and D copy, cut, paste and duplicate a block (paste lands at the playhead); Delete removes; Cmd Z and Shift Cmd Z undo and redo; Space plays. Cmd-drag a bar or node to drag off a copy. Right-click a bar or node for the same.
- **Precise control.** Nodes snap to a grid as you drag; hold Shift to place them freely. On the timeline Shift still gives fine steps.
- **Links you can redraw.** Click a link to pick it (Delete removes it), drag it onto another node to redraw it, drop it on empty canvas to remove it, or right-click it for Delete link.
- **Icons.** Every kind of block has its own small drawing, on the timeline bars, the node headers and in the menus.
- **Blocks never hide each other.** Blocks that overlap in time on one card now sit in lanes, one under another.
- **Blender….** A button in the animation bar saves the cards, their holders, the camera and every keyframe as a .glb at real size (metres), with clear plastic for holders. In Blender, File > Import > glTF 2.0.

## 2.36.0 · Animate: a timeline and nodes · 20 Oct 2026

- **Your own animations.** In 3D, Animate… (top left) opens an editor under the view for one card or several (Cards… changes them). An animation is built from blocks: card moves (Flip, Flip over the top, Spin, Sway, Hop, Move, Tilt, Entrance, Outro, and Each in turn, which runs a move down the cards one after another), arrangements (Stack, Row, Fan, Circle), animations of the set (Flip through the stack, Lift off the stack, Wave of turns, Round the circle, Spread and gather) and camera moves (Push in, Pull back, Orbit, Camera tilt, Pull focus).
- **Timeline.** A track per card and one for the camera, each block a bar from its start to its end. Drag a bar to slide it, its right end to change its length (Shift for fine steps), the ruler to scrub; double-click a track to add a block there at that moment; Delete removes the picked block; Space plays; Cmd-scroll zooms.
- **Nodes.** The same animation as a graph, card nodes on the left. Drag from a node's right dot to another's left dot: the second then acts on every card that reaches it and starts when the first ends, so Card → Flip → Stack flips the card and then stacks it. Drag a link's left end away to break it, right-click the canvas to add a node there, drag the canvas to pan, scroll to zoom, F frames everything. A link that would make a loop is refused.
- **One animation, two views.** Every edit in either shows in the other at once, with Undo and Redo, the properties of whatever is picked (delay, length and its own numbers) on the right, and the whole animation saved as you go and reopened next time.
- **Nothing jumps.** A card's pose is where the latest arrangement put it plus what its moves add, so one block hands over to the next smoothly, and the camera frames the arrangement rather than chasing a card that has been thrown out of shot. Foil, light, reflections, the film finish, the backdrop, the floor, holders and depth of field all apply.
- **Export video…** renders the whole timeline at your size, frame rate, quality and motion blur from Settings, Videos. A first animation is made for you when you start: the cards drop in, gather into a stack and are flipped through, the camera pushing in a little.

## 2.35.4 · Squared-up stacks · 20 Oct 2026

- **Cards straightened in a stack.** In Flip through the stack, Lift off the stack and Spread out and gather, the stacked cards had a slight random tilt and stepped a little down and to the side, so from head on you could see the cards behind before their turn. Every card now starts and rests squared up, exactly behind the one in front, so only the front card shows until it moves.

## 2.35.3 · Head on · 20 Oct 2026

- **Every group starts head on.** Each animation used to add its own camera angle (the stack seen from 22° to the side, the circle and the others from a little above) before your Turn and Tilt, so 0°, 0° was not straight on. Now 0°, 0° is exactly head on for every animation, and Turn and Tilt move from there.

## 2.35.2 · An easier group camera · 20 Oct 2026

- **Numbers beside the sliders.** Turn, Tilt and Distance each have a box showing the exact value, which you can also type into (press Return). A 0°, 0° button puts the camera back.
- **Flip through the stack, smooth.** The card going over the top used to land straight and square at the back and then jump into its place (and the front card jumped straight from its slight tilt as its turn began). Every card now travels from one resting place in the stack to the next, keeping its own slight tilt, slides down behind the others, and the rest step forward once it is clear, so nothing jumps.
- **Always starts at 0°, 0°.** Every group you show and every animation you switch to starts with Turn 0°, Tilt 0° and Distance 100%, the animation's own framing, instead of keeping the last camera.

## 2.35.1 · Groups in the light · 20 Oct 2026

- **No more dark veil over a group.** Each card's soft shadow was drawn on its own backdrop just behind that card, so once cards sat at different depths (a stack, a ring, or any group turned with the camera's Turn and Tilt) the shadows of the front cards fell across the cards behind them, dimming them like a dark moving film. The shadows now fall on one backdrop behind the whole group, each still under its own card, so every card gets the full light.

## 2.35.0 · Lift off the stack, a camera for groups · 20 Oct 2026

- **Lift off the stack.** A sixth animation for several cards: from a neat stack the front card lifts up and out of the shot, then the next, until none are left, and then they come back down onto the stack in turn, so it loops without a seam.
- **Your camera on a group.** The bar over a group has Turn, Tilt and Distance: turn round the cards, look down on them or up at them, move in or step back, on top of each animation's own framing. It is used in the view and in the video, remembered, and Reset goes back to the animation's own camera.
- **The lens on a group sees the holders.** With depth of field on, a group in slabs or top loaders was soft all over, since the lens only knew where the cards were and took the labels and plastic for far background; it now measures the holders too, so the cards in focus and their slabs are sharp together.

## 2.34.3 · Fixes · 20 Oct 2026

- **Inspector buttons fit their words.** Buttons in a grid (Background, Holder, the light setups and the rest) were squeezed shorter than their text on a Mac, cutting the words through the middle; each is now tall enough for its text at the panel's size.
- **A colour replaces the photo.** Picking a background colour while a backdrop photo was in use did nothing you could see; it now clears the photo and shows the colour, and no colour shows as picked while a photo is in use.
- **The slab's whole shadow.** The soft shadow behind a slab was cut off along its bottom, since it was sized for a bare card; it is now sized for whatever the card is in, alone or in a group, with the same softness.
- **Focus follows the tours.** With depth of field on (or a focus pull), the corner and edge tours, the pan and the reel now focus on the corner or edge the camera is on, so the rest of the card falls soft and the focus travels with the camera.
- **No scratches.** The hairline scratches are gone from every holder, slab included; the fine surface texture that breaks up highlights stays.
- **Fan out like a hand, smoothly.** While the hand was open each card swung on its own, so neighbours passed through each other and the stack order flipped, and the swing stopped dead as the hand closed. The whole fan now turns as one, easing in and out.
- **Several cards with depth of field on a Mac.** The distance pass behind the group's lens used a buffer format some Macs refuse; it now uses the 16-bit format the Mac's exports already use, and if a Mac still refuses it the group renders without the lens rather than wrongly.
- **Label text fits.** A long condition such as Moderately Played is set smaller until every word fits its column, instead of losing its first and last letters, and a long first line (a Carddass set name, say) gets smaller type before it is cut short.

## 2.34.1 · A true top loader · 20 Oct 2026

- **Cut corners.** The top loader's corners are now cut off at 45 degrees (4.5 mm), as on a standard 3 × 4 in top loader, instead of rounded, each cut a crisp flat with its own highlight; its edges are still eased slightly.
- **True depth.** A 35 pt top loader holds a 35 pt (0.89 mm) card between two walls of about 0.45 mm, so it is now 1.8 mm thick in all, down from 1.9 mm, with the card resting at the bottom of the pocket. Outside it stays 3 × 4 in (76.2 × 101.6 mm). The sleeve-and-loader holder and the sleeving moves use the same shape.

## 2.34.0 · Sleeving moves, a slab that reads as plastic · 20 Oct 2026

- **Sleeve it, top load it, take it out.** Four moves, on the Camera menu to play live and in Export's Motion menu for videos: Sleeve it (a penny sleeve slides up over the card, open end first), Sleeve it, then top load (then a top loader rises over the sleeved card), Out of the top loader and sleeve (the same, backwards) and Out of the sleeve. The card stays in the middle as the hero while the holders slide on and off, the camera widens to keep everything in shot and closes in as they settle, and the group turns a little as things move so you see their depth. Played live, the card is left in the holder the move ends in.
- **Sleeve + loader.** A new holder in Inspector, Scene: a penny sleeve inside a top loader, at true sizes, the way most cards ship.
- **Recessed windows.** The slab's windows over the label and the card now sit below the surround, each ringed by a rounded slope that bends the light like a moulded step, with a bright lip at the top edge and a little shadow at its foot.
- **Less like glass.** The slab, top loader and sleeve have a soft milky haze, uneven in a slow mottle and thicker at the slab's rim, a slightly stronger body tint, and reflections that are never mirror-sharp, so they read as moulded plastic.

## 2.33.1 · A finer slab · 20 Oct 2026

- **Standard PSA holder size.** The slab is now 3 1/4 × 5 1/2 in outside (82.6 × 139.7 mm), as published sizing guides give for a standard PSA holder, and 6 mm thick (guides put it between 5.5 and 6.4 mm). The card sits lower to match, 14.6 mm under the slab's centre.
- **Rounded edges.** Every edge of the slab is rounded over (1.4 mm) instead of cut square, so light rolls round it as a soft highlight; the top loader's edges are eased slightly too.
- **The pieces inside.** A clear inner frame holds the card in place, 3.2 mm round it and 1.5 mm thick, and a second frame holds the label, each with frosted cut edges that catch the light and a faint tint where you look through them.
- **A card-width label.** The label is now as wide as the card (63 × 21 mm) and drawn in that shape, so its type is no longer squeezed.

## 2.33.0 · Several cards together, real acrylic · 20 Oct 2026

- **Several cards at once.** In 3D, Several cards… (top left) picks 2 to 12 cards, from this batch or exported earlier, in the order you tick them, and animates them together in a seamless loop. Five animations: Flip through the stack (the front card lifts, turns over the top and drops in at the back), Round a circle (the cards on a turning ring, facing out), Fan out like a hand (open, hold, close), Wave of turns (each card turning a full circle a beat after its neighbour, in two rows past five cards) and Spread out and gather (from a neat stack into a row and back). A bar at the top switches the animation, changes the cards or goes back to one card; dragging turns the whole group.
- **Everything carries over.** Foil, light, room reflections, drifting light, the film finish, the backdrop photo, the glossy floor (each card reflected, with its own contact shadow) and holders, each slab with its own card's label. Depth of field works on the group too, measured per pixel, so the cards behind the one in focus go soft (for a ring, the card nearest the camera). Layers stay a one-card feature.
- **Video of several cards.** Export, Video of several cards… (and Video and Reel while a group shows) renders whole loops at your size, frame rate, quality and motion blur from Settings, Videos, as many loops as fit your usual length; the Reel is 1080 × 1920.
- **Acrylic that reads as acrylic.** The top loader and slab now have a body: a faint green-grey that deepens with the plastic's thickness and with the angle you look through it, strongest through the cut edges and the slab's rim, the way real acrylic tints what is behind it. The surface has a fine orange peel that breaks up highlights and the odd hairline scratch that only shows when it catches the light, and light runs along the polished outside edge.

## 2.32.1 · Holders at true size, a slab you would recognise · 20 Oct 2026

- **True thickness.** A penny sleeve is now half a millimetre in all (2.5 mil film each side of a 0.3 mm card), 2 5/8 × 3 5/8 in, so from the side it is almost invisible, as a real one is. A top loader is a standard 35 pt: 3 × 4 in and 1.9 mm thick. A slab is the common graded size, 3 1/4 × 5 3/8 × 1/4 in (82.5 × 136.5 × 6.4 mm). Each holds the card where a real one does: resting at the bottom of the sleeve and top loader, in its own well under the label in the slab.
- **A moulded slab.** The slab now has a thick rim that steps down to a thinner window, a well for the label and a well for the card, each edge a fine line that catches the light, and the rim reflects more than the clear window over the card.
- **A label like a real one, without a grade.** Laid out as a graded label reads: year, game and set on the top line, the card's name large, its number and variety under it, and your condition (Near Mint, Lightly Played...) on the right, which a switch can hide. No number grade and no grading company's marks. The fields fill themselves from what CardCrop knows of the card (its identification and the condition you set) and you can override any of them, remembered per card.
- **Reflection covers the holder.** The Reflection slider under Light now sets how much the sleeve, top loader or slab reflects too.

## 2.32.0 · Holders, drifting light, the reel · 20 Oct 2026

- **Sleeve, top loader, slab.** Inspector, Scene, Holder puts the card in a clear penny sleeve, a rigid 3 × 4 in top loader or a graded slab, each at its real size, reflecting the room, brighter at grazing angles, with the thick acrylic edges of a top loader and slab catching light. The view frames the whole holder, the slab turns round its own centre, and its shadow and floor reflection come with it.
- **The slab's label.** A plain label of CardCrop's own design (not any grading company's): the title (the card's name unless you type one), a second line for year, set and number, and on the right the grade and its words, shown only when you enter a grade. Remembered per card. The back of the label shows plain stock.
- **Drifting light.** Inspector, Light, Movement, Light drift: the lights and the room's reflection drift slowly round the card, so highlights and foil keep moving even when the card is still. In videos the drift completes whole cycles, so loops stay seamless.
- **Reel for Instagram and TikTok.** Export, Reel…: one click to a 1080 × 1920 video of about 17 seconds: your last entrance (Pop if none), focus pulled onto the card, a sway and a full turn with a gentle push in, then close on each corner and back to the whole card, in your current look and holder, with motion blur when it is on in Settings. The same sequence is in Export's Motion menu as Reel, for other sizes.

## 2.31.0 · Film finish, room reflections, floor, camera moves · 20 Oct 2026

- **Film finish.** Inspector, Camera, Film: Bloom (a soft glow round the brightest parts, the foil's flashes above all), Vignette and fine Grain, in the view and in every export. On lightly by default; set any to 0 to turn it off.
- **Room reflections.** Inspector, Light, Reflections: the laminate and the foil reflect a real room instead of drawn light strips, sharper on a glossy finish and stronger at grazing angles, and the foil flares where the room is bright. Without a backdrop photo the room is a photo studio (a tall softbox, a strip light, a top light); with one, the card reflects your photo, so it picks up the colours behind it.
- **Motion blur.** A switch in Export and in Settings, Videos: each frame blends eight moments across a film camera's half-open shutter, so spins and fast entrances smear the way a real camera records them. Renders take about eight times as long.
- **Pull focus.** Camera has a Focus point (nearer or farther than the card's centre) and Pull focus, which starts focused behind the card and racks onto it; Export can open a video that way. It brings its own lens, so it works with Depth of field off.
- **Glossy floor.** Inspector, Scene, Floor: the card stands on a glossy surface and is reflected in it, fading with depth, with a contact shadow under it, and the framing lifts to fit the reflection in.
- **Camera moves.** A Camera menu on the bottom bar plays them live, and Export has them: Slow push in, Fast push in, Pull back reveal and Breathe in and out ride on any motion (Export, Camera); Corner tour (front, or both sides with a flip between), Edge tour and Pan top to bottom are motions of their own (Export, Motion), going close to each corner and edge for buyers checking condition. Picking a tour lengthens the video to fit it.
- **Parallax from the camera.** With layers on, each layer's slide now comes from the real line of sight at each point of the card, not only from how the card is turned, so pushing in close or panning to a corner shifts the layers against each other the way a real camera would.
- **Recording keeps everything.** Record now captures entrances and camera moves, which it used to drop.

## 2.30.0 · The 3D inspector · 20 Oct 2026

- **One inspector, docked.** The 3D view's floating Look… panel and the controls scattered over the card are now a single graphite Inspector beside the view, so it never covers the card. Five tabs, each one job: Material (finish, strength, pattern and its sliders), Layers (source, foil per layer, depth and light, your PNGs), Light (the setups and how the card responds), Camera (depth of field, snap to face, exact turn and tilt with 15°, 30° and 45°), and Scene (background colour and backdrop photo). The Inspector button hides it for a full-width stage, and it remembers the tab you were on.
- **Larger, quieter type.** Every label is a size up, values sit in mono on the right of their name with the slider full width beneath, sections have spaced small caps headings, and the open tab has the one lime accent.
- **A cleaner stage.** Top right holds only Record, Inspector and a lime Export with a menu (video or 3D model). The bottom bar keeps just the moves, grouped as you use them: Front, Back, Flip; Spin 360, Sway, Turntable; Entrance, Outro; Reset.
- **What you see is what you export.** The background colour is now set in Scene and used by the view as well as by videos, with Black, Stone and any custom colour added to Dark, Light, White and Lime. The Export dialog keeps a custom colour instead of resetting it.

## 2.29.0 · Backdrop photo · 19 Oct 2026

- **Your own photo behind the card.** Look…, Lighting, Backdrop photo: pick any photo (JPEG, PNG, HEIC, TIFF, WebP) and it fills the background, cropped to fill whatever shape the view or video is, blurred and darkened so the card stays the subject. Photo blur runs from a hint of the scene to pure colour and light, Photo dim from as shot to nearly black. The card's shadow falls on it, depth of field works over it, and videos and stills use it in place of the background colour (the colour menu in Export greys out while a photo is set). ProRes 4444 still renders a transparent background. The photo is remembered; Clear goes back to the colour.
- **Sizes.** Use a photo at least 1080 px on its short side, or 2160 px for 4K videos, and shoot or crop it in the shape you export (1:1, 4:5, 9:16 or 16:9) so the crop keeps what you want. A smaller photo gets a note when you pick it; blurred, it still works.

## 2.28.0 · Lens depth of field, parallax per layer · 19 Oct 2026

- **Depth of field over the whole view.** Look…, Lighting has a Depth of field switch that works like a real lens focused on the middle of the card: face-on everything is sharp, and as the card turns its near and far edges go soft, the card's silhouette, its frame, text and layers alike, with a band around the focus kept crisp. Focus blur sets how fast it falls off. It runs as a pass over the finished frame, so videos and stills (16-bit ones too) get it as well.
- **Every layer slides at its own speed.** Your PNG layers no longer move as two sheets: each one sits at its own depth, the backdrop deepest, the card face on the surface, and the others spread between or floating above it, so turning the card shows them drifting apart. The Layers panel has a Parallax slider for whichever layer is picked, from Back (drifts with the backdrop) through Surface to Front (floats over the card and slides the other way). It is remembered per card, and Reset clears it.
- **Backdrop blur.** The Layers switch that only softens the backdrop is now called Backdrop blur, so it is not confused with the new lens.

## 2.27.0 · Depth of field · 19 Oct 2026

- **Depth of field.** Look…, Layers has a Depth of field switch: the camera focuses on the subject and the backdrop goes soft behind it, like a lens with a shallow depth of field, so the layers read as farther apart. Blur sets how soft, from a hint to a strong bokeh. The subject and the frames stay sharp, it works with your own PNGs and with the automatic split, and videos and exports use it.

## 2.26.1 · Every layer movable, clean edges · 19 Oct 2026

- **Move and size the frame files too.** In Arrange and order layers…, click any layer in the list (the card face, the border, the subject or the backdrop) and drag, scroll or type to place it. Frame files move in steps of the card's size; the subject and backdrop in steps of the art window. The Layers panel's sliders have a layer menu with every file in it.
- **No yellow card behind the card.** A PNG with faint, nearly invisible pixels across its canvas (your card.png has them) was measured by those pixels, so it came out smaller than the border and the border showed around it like a second card. Each layer is now measured by its solid picture alone, so the card face and the border line up, and stray specks around a cut-out no longer shift it.
- **See-through corners.** In the arrange preview, outside the card's rounded corners is now transparent instead of filled with the border colour.

## 2.26.0 · Layer order · 19 Oct 2026

- **Put any layer on top.** Arrange and order layers… now has a Layers list, top to bottom: drag a layer, or use Up and Down, to restack it. The frame starts on top, over the subject; move the subject above the card face (and under the border, if you like) for a pop-out card, with the subject breaking over the name bar and the edge of the art window. Several frame files can be put in any order among themselves. The backdrop always stays at the bottom.
- **The 3D view follows the order.** Frames above the subject cover it as it moves; frames below it stay behind it, so a popped-out subject floats over the card face as the card turns. The order is remembered per card, along with the layout.

## 2.25.0 · Layered cards, arranged by hand · 19 Oct 2026

- **Layers are back, built around your assets.** Look…, Layers, Use my PNGs… takes a folder of PNGs that no longer have to share one canvas. The frame (card.png, border.png or any file named frame, card, border, overlay) sets the card: its opaque area is the card and the biggest transparent area inside it is the art window. Several frame files are stacked, so a card face and a separate border both work.
- **Any size of backdrop and subject.** A backdrop is fitted to fill the art window and continued past its edges, so a deep parallax never shows where the picture ends. A subject is fitted inside the window, standing on its bottom edge. PNGs drawn on the frame's own canvas still stay exactly where you drew them.
- **Complete control of placement.** Arrange by dragging… opens the card flat: pick Subject or Backdrop, drag to move it, scroll to resize, arrow keys to nudge (Shift for bigger steps), or type exact size and position. Size, Left / right and Up / down sliders in the Layers panel do the same without leaving the 3D view. The layout is remembered per card, and Reset puts a layer back to the automatic fit.
- **No more frame text on the subject.** A subject that slides with parallax took its colour from the finished card face, so it could pick up the frame's printing, the overlay seen on Cheren's head. It now takes its colour from the art alone.
- **Clean card corners.** Outside the frame's rounded corners the card takes the frame's edge colour, so no art shows at the corners.

## 2.24.1 · Store category in the listing editor · 19 Oct 2026

- **Change a live listing's store category.** Store, Listings has a Store category field in the editor, showing the category the listing is in now, with your categories listed as Pokemon › Singles and so on. Pick another (or None) and Save to eBay moves it. It works for CardCrop's listings and ones made in Seller Hub. The button beside it reads your categories from eBay again; the first time you open a listing they are read for you.

## 2.24.0 · Picks up where you left off · 19 Oct 2026

- **The batch survives a crash.** Every few seconds, and when you quit, CardCrop saves the batch you are working on: every photo, with its edges, rotation, card name, side, condition, identification and carousel crop, which photo you were on, and any titles you edited. The next time it opens, the batch is back as it was, with a note saying how many photos it restored. Photos moved or deleted since are skipped and counted.
- Shots from the camera were always saved to disk the moment they were taken; what was lost in a crash was the work done on them, and that is what is kept now. Clearing the list (and not undoing it) starts the next session empty.

## 2.23.2 · Presets and auto-upload fixed · 19 Oct 2026

- **Edit presets work again.** The saved camera settings added in 2.22.0 reused the name of the Edit tab's preset list, so that list was left empty and could not be picked from, and saving a preset of your own stored the wrong settings. They now have separate names, and both work.
- **Auto-upload is its own switch again.** The new Auto-capture switch had taken over the name of the Auto-upload button, so auto-upload followed the auto-capture setting. Each now works on its own.
- **Floating messages stay in place on resize.** The short-screen change in 2.22.2 replaced the code that keeps notices and floating bars in place when the window is resized; both now run.

## 2.23.1 · Full camera values · 19 Oct 2026

- **Camera lists show whole values.** The aperture, shutter and ISO lists opened only as wide as their tile, so f/3.5 read as f…5. Each list now opens wide enough for its longest value, and never shortens one.

## 2.23.0 · Cleaner RAW files · 19 Oct 2026

- **Capture sharpening.** RAW photos are now sharpened lightly on brightness alone, the step every raw converter applies by default to undo the softness of the camera's sensor filters, and which CardCrop was leaving out. Fine print and edges come out crisper; colour is untouched.
- **No false-colour speckle.** Demosaicing leaves coloured specks along fine print and halftone edges; they are now cleaned from the colour channels only, about 45% less on a real a6700 shot, with no loss of detail.
- **Foil highlights recovered.** A highlight the sensor clipped is rebuilt from the channels that did not clip, so a holo hot spot fades to white like real shine instead of going flat or pink.
- Together they add about half a second to opening a RAW file. The Tone sharpen slider still works on top, for when you want more.

## 2.22.2 · Fits short screens too · 19 Oct 2026

- **The window no longer grows past the Dock.** The side rail (with the 3D button back) and the Shoot column set a minimum height taller than the screen, so the window kept growing back past the Dock. On a short window the rail now drops its labels and keeps its icons, and past that it scrolls, as does the Shoot column; nothing sets a height the screen cannot fit.

## 2.22.1 · Carousels keep your edits · 19 Oct 2026

- **Carousel only uses your tone edits.** In Carousel only, slides were written straight from the photo, so camera shots (RAW files especially) came out flat, without the exposure, contrast, warmth or sharpening you set in Tone. Your tone edits are now applied, along with your crop and rotation, as they always were for the eBay export. With every tone slider at zero, a photo you edited elsewhere is still left exactly as it is.

## 2.22.0 · Smarter live view · 19 Oct 2026

- **Auto-capture (N).** Shoot, View, Auto-capture: put a card down and take your hand away, and once its edges are locked and it has sat still (0.5 to 2 seconds, your choice) the camera focuses and shoots. Swap in the next card, or take it away and put another down, and it shoots again; the same card is never shot twice, because each card's look is remembered and compared. A bar under the message fills while it waits.
- **Live edges and centering (V).** The card is found in live view several times a second: its outline turns green when the edges are locked, with left/right and top/bottom centering, so a bad crop or an off-centre card shows before the shot.
- **Saved camera settings.** Save the camera's aperture, shutter, ISO, EV, white balance, Kelvin, focus mode and focus area under a name (Holos, Regular cards), and pick one from the list or with Cmd+1 to Cmd+4 to set the camera in one go. Anything the camera's current mode will not let CardCrop change is named.
- **Focus peaking (X) and corner loupe (Q).** Peaking makes sharp edges glow magenta over the live view; the loupe shows the card's four corners magnified, top right, with the peaking on them too, to check the corners are crisp before shooting.

## 2.21.0 · Cards in no database · 19 Oct 2026

- **Enter it yourself.** Identify has Not listed? Enter it yourself… for cards no database has, like Carddass, Topsun or odd promos. Type the game, name, set or series, number, year, rarity or finish, maker and language, and the card lists like any other: the title is built as you type (Charizard No. 6 Carddass Part 3 Prism Japanese 1997 Bandai Pokemon Card), the item specifics carry the set, year and maker, and the price suggestion comes from eBay listings found with those words. Reopening Identify on such a card lets you edit what you entered.

## 2.20.1 · Fits smaller screens · 19 Oct 2026

- **The Edit column no longer runs off the screen.** The window's smallest width was set by the widest page (Store, about 1,160 points with the side rail), even while you were in Edit, so on a narrower screen the right column was cut off. Each page now sets the window's smallest size only while it is showing: Edit fits in about 730 points. Store, List, Market, Reports and Settings scroll sideways on a screen narrower than they are, instead of being cut.

## 2.20.0 · Store categories · 19 Oct 2026

- **Pick the store category before uploading.** List has a Store category menu in the action bar for every ticked card, and each card's ••• menu has one too. The menu shows your eBay Store's categories and subcategories, read from eBay with Read my store categories from eBay, and the chosen one shows under the card's name.
- **A default.** Settings, eBay sets the store category new listings go to; a card's own choice wins over it, and No store category leaves a card out of all of them.
- **Moves what is already up.** Changing the category of a card CardCrop already put on eBay, live or unpublished, moves that listing straight away. Uploads and the Seller Hub drafts file both carry the category.

## 2.19.0 · Yu-Gi-Oh! and One Piece, properly · 19 Oct 2026

- **Recognised whatever your usual game is.** When no Pokémon number is found, CardCrop now looks for a One Piece code and then a Yu-Gi-Oh! set code on every card, so a mixed batch identifies without switching the game first.
- **One Piece codes read as printed.** OCR reads OP as 0P and runs the rarity on ("0P05-119SEC"); CardCrop reads through both, which before meant many One Piece cards were not found at all. The printed rarity mark (L, C, UC, R, SR, SEC, TR, P) narrows the match.
- **The right version of a One Piece card.** One code can be a dozen cards: the regular print, Alt Art, Manga, SP, SP Gold, Wanted Poster, reprints. Each candidate's picture is compared with your photo and the closest comes first; when one is clearly the match it is picked for you, and when two look nearly the same (a Manga and its reprint) you choose. Versions are named the way sellers write them, promos and DON!! cards are now in the database, and each version keeps its own price.
- **Yu-Gi-Oh! rarities and editions.** The set code and 1st Edition or Limited Edition are read from the line under the art, with OCR's O and 0 mix-ups corrected. Rarity names are cleaned up (QCSR, Starlight Rare, Platinum Secret Rare, Collector's Rare and the rest), and a code printed in several rarities lists them all, so you pick yours; same art means the photo cannot tell them apart.
- **Titles, names and prices per version.** Titles carry the short forms sellers search for (QCSR, SEC Manga, SR Alt Art) and 1st Edition; Edition is an item specific. Card names include the version or premium rarity, so a QCSR and the Ultra Rare of the same code, or a Manga and the regular print, never merge into one card. eBay price comparisons only count listings of the same rarity or version.

## 2.18.0 · Local pickup · 19 Oct 2026

- **Local pickup on any listing.** Store, Listings has a Local pickup switch in the editor, saved with Save to eBay. eBay keeps local pickup in the shipping policy, not the listing, so turning it on moves the listing to a copy of its shipping policy with local pickup added, named after the original with "+ local pickup". The copy is made the first time and reused for every listing on that policy after, and turning it off moves the listing back. It works for CardCrop's listings and ones made in Seller Hub, as long as they use a shipping policy.

## 2.17.1 · The 3D tab is back · 19 Oct 2026

- **3D tab restored.** Only the layered cards (frame, backdrop and subject) are shelved; the 3D tab, its foil and lighting, entrances, outros and exports are back as they were. The Layers page is hidden from Look… and the layer models stay out of the build.

## 2.17.0 · Remove, undo, and the 3D tab shelved · 19 Oct 2026

- **Remove single photos.** Select one or more photos on the filmstrip (Shift and Cmd click work) and press Delete, or right-click, Remove from the list. The files stay on disk. Cmd+Z brings them back where they were, like the Finder, and that includes the whole list after Clear; Shift+Cmd+Z removes them again. Edge edits and removals undo in the order you made them.
- **List: upload again, or remove.** Each card in List has a ••• menu. Upload to eBay again re-sends a card after a failed upload or after its listing was deleted on eBay, and asks first when CardCrop has it as live. Remove from CardCrop takes out a card you listed by hand, so the double is gone; Remove in the action bar does the same for every ticked card, and Cmd+Z brings them back. When CardCrop had uploaded an unpublished copy, you can delete that copy on eBay at the same time. A live listing is never ended from here; that stays in Store, Listings.
- **Enter searches.** In Identify, Enter in the search bar runs the search and nothing else; it no longer picks the first result and closes the window.
- **Type over a price.** Clicking or tabbing into a price selects it, so typing replaces it instead of adding to it. This applies to every price box.
- **Videos settings.** Settings has a Videos page for the 360° videos that Add video makes in Store, Market and Reports: size up to 4K (square, story or wide), 30, 60 or 120 fps, quality, motion, entrance, outro, background and length. Listing videos are no longer held to 1080. A video over eBay's 150 MB limit is uploaded as a smaller copy, with yours kept as made.
- **3D tab shelved.** The 3D tab, its layers and the layer models are out of the app and the build. The renderer stays, since it makes the listing videos.

## 2.16.0 · Your own layers · 19 Oct 2026

- **Bring your PNGs.** Look… > Layers > Use my PNGs… takes a folder of transparent PNGs you made yourself (in Photoshop, say) and uses them as the card's three layers: the backdrop at the back, the subject over it, the frame on top. Files are matched by name: subject (or foreground, character), frame (or border, overlay) and backdrop (or background). Any of the three can be left out. Lighting, foil, depth and parallax work exactly as with the automatic split, and exports and videos use your layers.
- **Remembered per card.** The folder is remembered for that card, and a folder named "layers" inside a card's export folder is picked up on its own. Automatic goes back to the AI split. Your own layers need no model download.
- **No ghost text.** In the automatic split, the printed text is now also taken out of the backdrop, so text no longer appears twice when the backdrop slides behind it.

## 2.15.1 · Subject selection like Select Subject · 19 Oct 2026

- **Two detectors, merged.** The subject is now found by two models: the anime-art one (trainers and most Pokémon art) and a general salient-object one (items such as Ultra Ball, painted and 3D-rendered Pokémon). A model that only selects the art panel, as the anime one did on Ultra Ball, is ignored; the rest are merged, stray specks are dropped, and the edge is refined on the image itself so outlines and hair follow the art.
- **The art only.** The models are shown the art: inside the border, below the name bar and above the rule box. Shown more of the card, they selected the card or the whole art panel.
- **Text stays on the card.** Every line of printed text (the name, attacks, rule box, credits) is found with the card reader and kept on the surface, so a title like "Cheren" or "Ultra Ball" is never covered by the shifting art.
- The models download once, about 350 MB together. Layers made with the old model are rebuilt automatically.

## 2.15.0 · Layered cards · 19 Oct 2026

- **Frame, background and subject, each on its own.** Look… > Layers splits a card's face the way immersive digital cards are shown. The frame (border, name bar and rule box) stays on the surface. The background art sits deep behind it like a window and slides one way as the card turns, while the subject floats in front and slides the other, casting a soft shadow on the art behind it. Each layer has its own light (Subject and Backdrop) and its own foil switch (Frame foil, Back foil, Subject foil), with Depth and Frame width controls.
- **Found by AI, on your Mac.** The subject is picked out by a segmentation model trained on anime-style art (ISNet), run once per card with onnxruntime and remembered. The background behind the subject is filled in, so parallax reveals art rather than a hole. The model downloads once (about 170 MB), after asking. Layers work in the 3D tab, in exports and in listing videos.
- **Tidier Look panel.** Foil, Layers and Lighting are now three pages of the panel, so it fits any window.

## 2.14.2 · No more flashes on a turn · 19 Oct 2026

- **Steady light through a rotation.** The studio lighting could flash for a frame or two as the card turned, mostly just before it went edge-on, where glossy-highlight maths runs away on a sliver of card. Highlights now fade out as the card approaches edge-on, are never mirror-sharp, and are capped; the softbox reflection is broader and gentler; and the Dramatic key light sits further off, so it sweeps instead of snapping. Measured over a full turn, the largest frame-to-frame brightness jump fell from 79 to 6 levels in Studio (Classic is 2), and the light now changes gradually in every preset.

## 2.14.1 · Matte backs · 19 Oct 2026

- **Backs are card stock.** The back of the 3D card no longer takes the foil, the gloss, the softbox reflection or the sliding glare: it is lit as matte card, with only the faint sheen of printed stock, while the front keeps everything. This applies in the 3D tab and in every video.

## 2.14.0 · Video quality and colour · 19 Oct 2026

- **Correct colour.** Every export is now converted and tagged as Rec. 709, the colour space the card photos are in. Untagged H.264 converted with the older matrix is why exports could look a little washed out or shifted in QuickTime and browsers.
- **Five quality settings.** Standard H.264 (as before, plays everywhere), High H.264 (near lossless, rendered at twice the size and scaled down for finer edges and foil), HEVC 10-bit (rendered in 16-bit, so gradients, backgrounds and shadows do not band, at smaller sizes than High), ProRes 422 HQ 10-bit .mov for editing apps, and ProRes 4444 .mov with a transparent background, shadow included, to drop over anything in Premiere, Final Cut or After Effects. Only settings the bundled encoder supports are offered.
- **60 fps and 4K.** A frame-rate choice (30 or 60) and three 4K sizes: square 2160, story 2160 × 3840 and wide 3840 × 2160.
- **Listing videos stay safe.** Videos added to eBay listings always use H.264 at up to 1920 pixels, whatever you export for yourself, to stay inside eBay's formats and 150 MB limit.

## 2.13.0 · Studio lighting and 3D export · 19 Oct 2026

- **A real lighting model.** The 3D card is now lit by three placed lamps (key, fill and rim) that fall off across the face, with physically based highlights on the laminate, a softbox whose reflection slides across the gloss as the card turns, stronger reflection at grazing angles, slight light falloff at the rim, and a filmic tone curve.
- **Lighting presets.** Studio (the new default), Softbox, Dramatic, Sunset, or Classic for the old look, plus Gloss, Exposure and Shadow sliders. They sit with the foil controls in the panel now called Look….
- **A soft drop shadow.** The card throws a blurred shadow on the backdrop, sized to how it is turned and fading as it lifts away in an entrance or outro. It shows best on the light and white video backgrounds.
- **Export 3D.** The 3D tab exports the card as an OBJ for Blender, Cinema 4D and other 3D programs: the rounded outline at real size (63 × 88 × 0.32 mm, in metres), the front and back as PNG textures, and the edge as white card stock, with materials in a .mtl beside it.

## 2.12.0 · Outros · 19 Oct 2026

- **Nine ways out.** An Outro menu beside Entrance on the 3D tab: Drop out, Lift off, Slide out to the left or right, 3D flip out, Tumble out, Spiral away, Pop out and Toss away. Most are the entrances in reverse, so they start slowly and accelerate out of frame; the turning ones spin away while shrinking to nothing. In the 3D tab the card comes back a moment later.
- **Bookended videos.** Export MP4 has an Outro option next to Entrance. The outro takes the last 1.6 seconds and leaves from wherever the motion ended. Leave it at None for a video that loops without a cut. Listing videos use your last choice.

## 2.11.0 · Front and back pairs by name · 19 Oct 2026

- **Pairs match themselves.** Photos named as one side of a card are put to that card and side as they are added: CardCrop's own exports (name_02_front, name_03_back_NM) and plain names such as "Charizard front" and "Charizard back". An export also brings what its folder knows: the identified card, the back's condition and the price.
- **Your corrected edges win.** When a live listing's card is open in Edit, Add video and condition reports use those photos with the edges as you set them, rather than finding the card again in the folder. Fix the corners once in Edit, then make the video.

## 2.10.1 · Video titles eBay accepts · 19 Oct 2026

- **Upload reaches eBay.** The video address is now right: eBay took the request and only refused the title. Titles such as "Reshiram & Zekrom GX" were refused as markup (error 190016), so video titles now spell & as "and", drop quotes, # and angle brackets, and write Pokémon as Pokemon.
- **Drop in matches Rise up.** It now comes down from above with the same smooth settle, instead of bouncing.
- **Backs straight from your folders.** A back whose found outline was a few degrees off (the swirl, not the card's edge) skewed in videos even from export folders. In an export the card's sides now have to be parallel to within a degree, and a card running to the edge of the photo is still cut along its own sides.
- **Attaching to CardCrop's own listings.** Your log shows a video that did upload (to Scramble Energy) but could not be attached: eBay answered "Availability not found" (25604) because CardCrop sent back a read-only quantity breakdown eBay had included in the listing's inventory record. Records are now sent back with the plain quantity only, for videos, report photos and the listing editor alike.

## 2.10.0 · Entrances · 19 Oct 2026

- **Nine ways in.** The 3D tab has an Entrance menu: Drop in (falls from above and bounces), Rise up, Slide in from the left or right (turning to face you), 3D flip in (a turn and a half, landing with a little give), Tumble in (end over end), Spiral in (from far away), Pop (a springy scale-up) and Toss and catch (an arc from the left, spinning). Each lands face-on, and a click stops it.
- **In videos too.** Export MP4 has an Entrance option. The card arrives over the first 1.6 seconds, then the chosen motion plays in the time left. Listing videos use the entrance from your last export.

## 2.9.3 · Folders found by their eBay SKU · 19 Oct 2026

- **SKU matching.** eBay SKUs replace dots and spaces with hyphens (raifort-sv08.5-142 becomes raifort-sv08-5-142), so a third of your _BATCH21 listings were not matched to their folders and fell back to eBay's photos, which is where the skewed Store-tab videos came from. Folders are now matched either way: 38 of the 39 cards in _BATCH21 are found without asking. The rest are from older batches, and CardCrop asks for those once.

## 2.9.2 · Videos and reports from your own exports · 19 Oct 2026

- **Your folder first.** Add video and condition reports for a live listing now use the card's exported folder (full size, already straight) instead of eBay's downsized photos. The folder is found by SKU in your output folder and any source folders.
- **Asked, not guessed.** When the folder cannot be found, CardCrop asks you to choose it, or to go ahead with the listing's photos. The choice is remembered for that listing, and the folder above it is searched from then on, so the rest of that batch is found on its own.
- **Videos saved beside the card.** A video made from a folder is saved in that folder.

## 2.9.1 · One way to find the card in a photo · 19 Oct 2026

- **Exports are never re-cut.** The 3D tab, condition reports and calibration read cards exported earlier with the same picker as listing photos, so a sound rectangle inside the card (a holo's art window or text box) is no longer taken for the card itself. In a photo that is already about the card, an outline now has to cover most of it.
- **16-bit exports handled.** The plain-margin test now works on 16-bit PNG exports as well as JPEGs.

## 2.9.0 · Foil lab · 19 Oct 2026

- **Five foil patterns.** A Foil… button on the 3D tab opens a panel of patterns: Linear (the classic diagonal sheen), Radial (rings radiating out from a centre that follows the light), Sunburst (rays, like a cosmos or starlight foil), Ice (cracked-ice shards, each catching its own colour) and Glitter (fine flecks that flicker as the card turns).
- **Five controls.** Dispersion (one soft colour up to many tight rainbow bands), Scale (broad to fine), Saturation (silver to full colour), Response (how far the foil shifts as the card tilts) and Sparkle (the scattered glints). Reset returns to the classic look.
- **Used everywhere the 3D card is.** Settings are remembered, apply with Holo, Art or Reverse, and carry into exported and listing videos.

## 2.8.1 · Cards read right from any listing · 19 Oct 2026

- **Turned cards come out square.** A listing photo where the card sits at a slight angle on a plain background is now turned upright before use, instead of being cut as a box that left dark wedges in the corners of the 3D card and video.
- **Close-ups are not mistaken for the card.** Each listing photo is judged: a whole card found by a sound outline first, then a card on a plain margin, and only last a photo that merely has a card's shape, which could be a close-up. An outline whose opposite sides are not parallel (a holo pattern pulling a corner off) is no longer trusted.
- **The back is found without references.** Before you have reference backs, the clearly bluest card in a Pokémon listing is taken as the back, rather than whichever photo came second.

## 2.8.0 · Snap, video check, a thinner card · 19 Oct 2026

- **Center snap in 3D.** Let go of the card and it settles face-on, front or back, level and centred, with a slight overshoot; a fling now lands on a face instead of stopping at a random angle. Snap is a toggle beside Turntable, remembered between sessions.
- **No surprise video replacements.** Before rendering, CardCrop asks eBay which of the chosen listings already carry a video and lists them, with Replace or Skip. Video buttons on listings that have a video CardCrop added are ringed in lime.
- **Paper-thin card.** The 3D card is now about 0.3 mm thick, like a real card, instead of twice that.

## 2.7.2 · Straight listing photos, saved videos · 19 Oct 2026

- **No more skewed cards from listings.** Listing photos that are already the card (every CardCrop export) were being re-straightened from an outline the holo pattern could throw off, which slanted the card in reports and videos. Such photos are now used upright as they are, with only the plain margin trimmed; tested on ten of your exports, fronts and backs. A back CardCrop cannot recognise is taken from the photo after the front.
- **Thumbnails show the whole card.** Card thumbnails across Store, Listings and Market are fitted rather than cropped, with corners rounded the way a real card's are instead of a large radius that cut them off.
- **Videos are kept.** Each rendered MP4 is saved in the card's export folder, or in a Videos folder inside your output folder for listings made elsewhere, instead of a hidden cache.
- **Video upload, second try.** eBay's video service sits under the media address's v1_beta path; CardCrop now uses it and falls back to the address eBay's guide gives.

## 2.7.1 · Video upload fix · 19 Oct 2026

- **Add video works on a real account.** Videos were sent to eBay's image server, which answered "resource could not be resolved" (404). They now go to eBay's main API address, where the video endpoints actually live.

## 2.7.0 · Listings editor and your own prices · 19 Oct 2026

- **Store > Listings.** A second view of the Store tab lists every active listing, searchable by title or SKU and sortable by date, price, watchers or title. Quantity and price can be changed right in each row. Picking a listing opens an editor that reads the live listing and saves straight to it: title (with an 80-character count), price, quantity available, condition, and best offer with auto-accept and auto-decline. Video, Report, Open on eBay and End listing sit underneath. Works for CardCrop's listings and those made anywhere else.
- **Prices are yours.** Market no longer offers only the scan's suggestion. Every row has a price box you type into, saved to eBay when you press Return; clicking the market figure only fills the box. Alerts get the same box. In List, changing a live card's price now changes it on eBay too.
- **Video next to every listing.** Market rows, Most watched, Just listed and the Listings view each have a video button that renders the 360° loop with your last 3D settings, uploads it and attaches it. When it finishes, you are returned to the tab you started from.
- **A smaller sales trend.** The Store overview is now three columns: a compact sales trend above Recently sold, traffic in the middle, and Most watched above Just listed, each list with its own price box and video button. The lists get the room the chart had.

## 2.6.0 · Calibrated condition reports · 19 Oct 2026

- **Calibration before the first report.** Reports now refuse to run until the scoring has learned how you grade. Calibrate (Reports tab) measures every card you have already given a condition: your eBay listings, live and sold in the last 60 days, read with the condition each was listed at, and any export folders you point it at, such as a drive of batch folders. Where a listing's SKU matches an export, the full-size export is measured instead of eBay's copy.
- **Fitted to you.** An ordinal model chooses which measurements and which sensitivities agree with your grades, and then places each card on the NM to DMG bar. It is checked on cards it was not fitted on, and that agreement is shown on the Reports tab, with a list of the cards where it disagreed with you.
- **More to measure.** Wear is now read at three sensitivities, and on coloured borders as lost colour as well as added brightness, since whitening on a yellow front shows as fading before it shows as white. The back surface is also read at a softer threshold.
- **Slabs and repeats.** Graded slabs are skipped, and measurements are cached, so recalibrating only measures new cards.

## 2.5.0 · Live listings: reports and videos · 19 Oct 2026

- **Reports for live listings.** Reports > Live on eBay lists every active listing. Make report downloads the listing's own photos, finds the front and back among them (skipping the side-by-side hero and the corner close-ups), and draws the report. Add to live listing uploads it and makes it the listing's last photo, live. Ticked listings can be done in one go.
- **Add video.** Renders a 360° turn of the card from the listing's photos, with your last 3D export settings, then uploads it to eBay and attaches it to the listing. Ticked listings render one after another, each uploading while the next renders.
- **How listings are changed.** CardCrop's own listings update through their inventory record, and others through a revise of the listing's pictures or video.
- **Folder uploads get reports too.** List exported folders on eBay has a Condition reports button for the ticked folders, so reports are added before upload.

## 2.4.0 · Condition reports · 19 Oct 2026

- **The report.** A square listing image that scores the card the way graders think. Every card starts at 100 points and loses some for each flaw found in the photos. One segmented bar places the score among DMG, HP, MP, LP and NM, and a row per category shows what was taken off and why.
- **What is measured.** Only what one overhead photo can show reliably:
  - Centering, with the ratios for front and back.
  - Corners and edges, where wear is light specks measured against the card's own edge, so the cut line of the card stock never counts.
  - Back surface, compared with a clean reference built from your own backs.
- **No grade.** The image carries no grade, only the score and the condition band, with "Not a professional grade" at the foot.
- **Only when asked.** Never at export. You make one from Edit (Condition report, Ctrl+R), Shoot (Report on the last shot), List (Condition reports for ticked cards), the command palette, or the new **Reports** tab.
- **The Reports tab.** Lists this batch, the save folder and any folders you add, with a large preview, Add to listing photos, Remove from listing and Show in Finder.
- **Mismatch warning.** If a report lands in a different band from the condition you set, Edit warns under the condition buttons, and a batch lists the cards that disagree.
- **Design path.** The report went from a radar chart to a scored segmented bar, and dropped wording a buyer would not need.

## 2.3.0 · Detection and reliability · 18 to 19 Oct 2026

- **Dark-bordered backs.** On a plain background, detection now also compares colour with the background, so a navy Pokémon back on black is found at its true outer edge instead of at the artwork inside it. Tested on 20 of your raw shots: every back right, every front unchanged. On busy backgrounds the extra step stays out of the way.
- **Thumbnails.** List and filmstrip thumbnails are straightened exactly as the export is, so they always face the same way as the listing photo.
- **Publishing.** eBay's temporary "System error, try again later" on publish is retried, checking first that the listing did not go live, so nothing is published twice.
- **Failed publishes.** A card whose publish failed now shows Publish rather than a dead Upload button, and Upload explains itself when a card is already on eBay.
- **Sold pictures.** Recently sold thumbnails load: each sold item's picture is looked up once and remembered, and WebP pictures decode.

## 2.2.0 · Market and traffic · 18 Oct 2026

- **Market tab.** Every active listing in your store, CardCrop's and any other (identified from its title), priced against the market:
  - Top movers, highest first, today or over 7 days, with a bar per scan.
  - Price alerts for cards under or over market, or moving past your alert percentage, each with Use $x (updates the eBay price too), Sold on eBay research and Listing.
- **Nightly scan.** Runs at the hour you choose, catches up after a missed night, and puts a lime dot on Market plus a Mac notification when something needs a look.
- **Store traffic.** A panel matching Seller Hub's Traffic card: impressions, click-through rate, page views and conversion, each with daily bars that line up by day and its change on the prior 30 days. Below it, where views came from: On eBay against External, with the eBay sources in the tooltip.
- **eBay permission.** Traffic needs one more read-only permission, granted by reconnecting once. Existing sign-ins keep working until you do.

## 2.1.0 · The card in 3D · 18 Oct 2026

- **3D tab.** The front and back on a real rounded card with a thin white edge, lit, with a holo shine that follows the angle. The foil can be off, whole face, art window only or reverse holo, with a strength slider.
- **Moves.** Drag to turn it any way, with eased glides and spin-downs. Presets: Spin 360, Flip, Front, Back, Sway, Reset and Turntable, plus typed Turn and Tilt angles. It rests face-on at 0° and 0°.
- **Video export.** Export MP4 renders a 360° turn at an exact size: steady loop, eased or sway-then-spin; 2 to 30 seconds; square, portrait, story or wide; four backgrounds; H.264. Record captures whatever you do in the window.
- **Pairing.** A back not named yet is paired with the photo right after its front.
- **Fixes.** The Spin button now turns the card a full 360°, where it had done nothing. The Auto-upload button reads properly in dark mode.

## 2.0.0 · Store · 18 Oct 2026

The app starts reading your eBay account, which makes it a store tool rather than a photo tool.

- **Store tab.** KPI tiles (sales over 60 days, the last 7 days, to ship, active listings, watchers) with mini bars and changes. A daily or weekly sales trend in squares, Most watched, and Just listed.
- **Recently sold.** A table with search and CSV export, plus links to Seller Hub and Orders to ship.
- **Coverage.** Reads every listing on the account through eBay's Trading API, however it was made.

## 1.3.0 · Settings and tracking · 18 Oct 2026

- **Settings stage.** Four tabs: Tracking, Output, eBay and App.
- **Tracking.** Rebuilt from the output folder and eBay records, so it covers every card ever exported:
  - Cards and photos per day, as a heatmap, with streak and best day.
  - Conditions, eras, English against Japanese, games, and price ranges.
  - Value listed and live.
  - Ranges of 7 days, 30 days or all time.

## 1.2.0 · Batch speed · 18 Oct 2026

- **Auto-upload.** Each card that is identified, graded, priced and exported on both sides goes up to eBay unpublished in the background as you move on, so a batch ends with review and publish.
- **Selecting and progress.** All and None on every ticked list, and slim progress bars with counts (4/10) instead of status text.
- **Bulk (under $1) preset.** Only the front, the back and a light side-by-side hero, as JPEGs.
- **Visual polish.** A night-mode version of the logo, a new app icon, and pill buttons throughout.

## 1.1.0 · More games, English listings · 18 Oct 2026

- **Yu-Gi-Oh! and One Piece.** Identification by name or printed code (LOB-EN005, OP01-001), with their market prices.
- **English only.** Titles, item specifics and descriptions never carry Japanese text, and a Japanese card CardCrop cannot name in English asks you for the English name.
- **Publish from List.** Cards already on eBay show Publish N instead of uploading again.

## 1.0.1 · Fixes after the redesign · 18 Oct 2026

- **Photo uploads.** eBay photo upload server errors are retried, so a batch of six no longer arrives as three.
- **Upload loop.** Uploading no longer cycles through the list.
- **Spin boxes.** Price and spin boxes no longer collapse to an unreadable sliver.
- **Pills.** Buttons that should be pills now are on the Mac.

## 1.0.0 · The redesign · 18 Oct 2026

- **Interface.** A complete rebuild in light and dark: floating islands, pills, Doto numerals and a lime accent.
- **Three stages.** Shoot, Edit and List on a rail, with a command palette (Cmd+K) for everything the screens leave out.
- **Toasts.** Messages appear as toasts instead of pop-ups.
- **Text size.** Adjustable text size, remembered along with the theme.

## 0.9 · eBay listing · 18 Oct 2026

- **0.9.3** UX pass: a drafts file for every exported card, clearer status messages, and a reworked export flow.
- **0.9.2** Japanese cards: identified from their English names and priced.
- **0.9.1** List exported folders on eBay: list cards straight from folders exported earlier, with no shooting or exporting.
- **0.9.0** Upload to eBay as unpublished listings through eBay's API:
  - Account connection with the Cert ID kept in the Keychain.
  - Shipping, return and payment policies, and a ship-from location.
  - Photo hosting.
  - Review and publish.
  - Seller Hub drafts as an alternative route.

## 0.8 · Instagram · 18 Oct 2026

- **Carousels.** Three 4:5 slides at full resolution: the card on light grey, then a two-slide seamless close-up framed with P.
- **Carousel only mode.** For posts, and "Carousels from edited photos" for finished photos.
- **Presets.** Saved setting sets, including Already edited photos, and a switch for corner close-ups.

## 0.7 · Listing details · 17 Oct 2026

- **Condition grades.** NM, LP, MP, HP and DMG, set on the back and carried into filenames and listings.
- **Lens profiles.** Measured distortion and colour-fringe correction for your lens.
- **Smarter search.** Card search accepts a name, a number or both.
- **Drafts template.** Fills eBay's drafts template with every exported card.

## 0.6 · Auto shoot · 16 Oct 2026

- **Auto shoot.** The camera fires on its own once a card sits inside the overlay and everything is still, with adjustable match and stillness.

## 0.5 · Live view overlay · 16 Oct 2026

- **The overlay.** A card-shaped overlay on live view that you can move and resize, with grid modes and "match last shot" (it jumps to where the last card was detected).
- **Overlay presets.** Saved overlays on Cmd+1 to 4.

## 0.4 · Tethered shooting · about 15 to 16 Oct 2026

- **Tethering.** Sony a6700 shooting from inside CardCrop: live view, focus and shoot, aperture, shutter and ISO.
- **Straight into Edit.** Each shot lands in the edit list with its card already detected.

## 0.3 · Identify and price · about 14 to 15 Oct 2026

- **Identify.** Finds the card from its printed number (on-device text reading) or by name, using the TCGdex card database.
- **Pricing.** TCGplayer and Cardmarket prices, plus live eBay asking prices, with a suggested price.
- **Listing text.** Titles and descriptions built from the identified card.

## 0.2 · Listing-ready output · about 13 to 14 Oct 2026

- **Hero image.** Front and back side by side as photo 1.
- **Naming.** Numbered files in eBay listing order: hero, front, back, then eight corners.
- **Centering.** Measured from the printed border.
- **Editing tools.** Free corners or a locked 63 × 88 card shape, a loupe, saved corner spots, undo, and tone adjustments.

## 0.1 · MVP · about 12 Oct 2026

- **The core.** Drop in card photos (JPEG, PNG, HEIC or camera RAW), and each comes out as a flat, squared, perspective-corrected card plus four square corner close-ups, ready for an eBay listing.
- **How.** Automatic card detection with draggable corner handles, and a batch command for the terminal.

---

## How this file is kept

Each round of work adds an entry at the top.
- **Fixes only:** the last number goes up.
- **New features:** the middle number goes up.
- **A change in what CardCrop is:** the first number goes up.

The app's version lives in `app.py` as `APP_VERSION`.
