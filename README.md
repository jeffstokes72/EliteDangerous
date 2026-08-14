# EliteDangerous

## Architect Tracker
Displays commodities required, provided and needed when you land at a construction site, market or fleet carrier and tracks cargo in your fleet carrier and starship.
The focus is to create a simple to use and hands free tracker for system colonisation. I will be adding features often so check back here often. This was created using ChatGPT. It probably took me as long to create as a human could have programmed manually but I have no experience programming in Python or for the EDMC so it is kind of impressive.

<img width="833" height="593" alt="Screenshot 2026-03-20 192521" src="https://github.com/user-attachments/assets/04c893f3-c70b-4bbc-832b-5c4bed7b1abd" />

Dark mode

<img width="833" height="582" alt="Screenshot 2026-03-20 192537" src="https://github.com/user-attachments/assets/57065805-b590-4e85-bdc1-dcef7ab051d6" />

Light Mode

<img width="1121" height="813" alt="Screenshot 2026-06-11 194230" src="https://github.com/user-attachments/assets/8783bce0-6144-40a3-9726-ae3f78b6388b" />

Settings Window

### Discussion
https://forums.frontier.co.uk/threads/colonization-tool-architect-tracker.636854/#post-10621804

### Install Instructions
Quit EDMC first. Download <a href="https://github.com/jeffstokes72/EliteDangerous/releases/latest">ArchitectTracker_enhanced.zip</a> and extract it into EDMC's **plugins** folder. The zip already contains the `ArchitectTracker_enhanced` folder (no version in the name, no renaming). After unzip you must have:

`.../plugins/ArchitectTracker_enhanced/load.py`

not `.../plugins/ArchitectTracker_enhanced/ArchitectTracker_enhanced/load.py`.

**Plugins folder locations**
- Linux (normal install): `~/.local/share/EDMarketConnector/plugins/`
- Linux (Flatpak): `~/.var/app/io.edcd.EDMarketConnector/data/EDMarketConnector/plugins/`
- Windows: `%LOCALAPPDATA%\EDMarketConnector\plugins\`
- macOS: `~/Library/Application Support/EDMarketConnector/plugins/`

**Linux (copy and paste):**

```bash
# Use the Flatpak line instead if that is how you run EDMC.
PLUGINS="$HOME/.local/share/EDMarketConnector/plugins"
# PLUGINS="$HOME/.var/app/io.edcd.EDMarketConnector/data/EDMarketConnector/plugins"

mkdir -p "$PLUGINS"
cd /tmp
curl -L -o ArchitectTracker_enhanced.zip https://github.com/jeffstokes72/EliteDangerous/releases/latest/download/ArchitectTracker_enhanced.zip
unzip -o ArchitectTracker_enhanced.zip -d "$PLUGINS"

# Must print OK.
test -f "$PLUGINS/ArchitectTracker_enhanced/load.py" && echo "OK: load.py is in the right place" || echo "BROKEN"
```

If you previously installed as `ArchitectTracker` (or `ArchitectTracker-2.x`), delete that old plugin folder so EDMC does not load two copies. Your construction sites and market library stay in `~/.config/ArchitectTracker/` (or the equivalent on Windows/macOS) and are not touched by reinstalling.

**If the settings tab is missing**
1. Confirm `load.py` sits directly in `.../plugins/ArchitectTracker_enhanced/` (command above).
2. Confirm you used the same plugins folder EDMC actually reads (Flatpak vs normal install).
3. Check EDMC's own log and `~/.config/ArchitectTracker/EDMC_Architect_Log.txt` for an import or startup error.
   A known cause was mixing pack/grid in the prefs UI; that is fixed in 2.0.

### Usage
+ When you land at a construction site the plugin will (after a few moments) list all the commodities and amounts required, provided and needed. You can switch between sites from the dropdown list in the upper left or the ">" button. The window will resize itself to fit all the commodities.
+ The "Pref Market" column displays either the cheapest, closest or alternate market where that commidity has been found. This list is further filtered by orbital or surface markets. See "Prefered Markets" section below for more information.
+ To display\update your fleet carrier cargo, open the "Carrier Management" in-game tool. The quantities will appear after a few moments (this can take a while and occasionaly display incorrect number). If you are also selling commodities from your fleet carrier, you will need to update this list as needed (sales are not tracked).
+ Starship cargo will be displayed automatically.
+ The shortfall column displays how much of a commodity you still need to aquire. Click the Shortfall header (or any other header) to sort the list.
+ The Distance column shows how far in light years the preferred market is from the construction site.
+ Settings are available in the E:D Market Connector under File menu->Settings->ArchitectTracker tab. You can choose whioch columns to display, set the text displayed in the column header and other settings (see screenshot above).
+ Optional in-game overlay: with <a href="https://github.com/pan-mroku/edmcoverlay2">EDMC Overlay2</a> (Linux), <a href="https://github.com/inorton/EDMCOverlay">EDMC Overlay</a>, or <a href="https://github.com/SweetJonnySauce/EDMC-ModernOverlay">EDMC Modern Overlay</a> installed, enable "Show list on in-game overlay" in settings. A two-column table (commodity | amount needed) paints on the left side of the game window. The overlay position dropdown places it top left, mid left, or bottomish left.
+ Rows are highlighted (see screenshots above) depending on where you are docked, rows are highlighted to indicate:
  + Markets - market is selling the item and you have shortfall.
  + Fleeet Carrier - site needs it and fleet carrier has some AND starship does not have enough.
  + Construction site - site needs it and starship has some.
+ Closing the Architect Tracker window will stop the sites, commodities and markets from being tracked. This is handy if you're landing at markets but don't want the information to override your current closest\cheapest information.
+ Buttons on the UI:
  - <b>X</b> - deletes currently shown construction site. Disabled when -ALL- sites are listed.
  - <b><</b> or <b>></b> - changes to previous or next site in list. Wraps around list.
  - <b>$\Ly\Alt</b> - toggles between showing the cheapest, closest or alternate markets in the preferred market column. See "Preferred Markets" section below for more information.
  - <b>O\S</b> - toggles between showing orbital or surface markets in the preferred market column. See "Preferred Markets" section below for more information.
  - <b>Pause</b> or <b>Unpause</b> - this button next to the Carrier name will pause or unpause updating the fleet carrier cargo quantities from Fdev's fleet carrier companion api. See section below.

### Importing Nearby Markets
- The "Pref Market" column only knows about markets you have personally docked at. The settings tab can fill in the rest: press "Import market data now" and the plugin looks up the markets around your construction site and adds their prices to the same list.
- Set how far to look (5 to 50 ly, 25 by default), whether you want orbital markets, surface markets or both, and a landing-pad filter:
  - **Large pads only** — starports and other L-pad markets (excludes outposts).
  - **Large and Medium** — also keeps medium-pad markets such as outposts (the default).
- The search is measured from your construction site, not from wherever you happen to be.
- The prices come from <a href="https://spansh.co.uk">spansh.co.uk</a>, which collects what other commanders report to EDDN. They are a donation funded community service, so the plugin only asks when you press the button, at most once a minute, and stops after the 200 markets nearest your site.
- Out in colonisation space most markets have not been visited by anyone in months, so expect the prices to be older than the ones you collect yourself. The plugin tells you how old the oldest one was and ignores anything over a year. Docking at a market always replaces the imported price with what you actually saw.
- Fleet carriers and megaships are left out on purpose because they move.

### Preferred Markets
- The "Preferred Market" column displays markets you have found that sell construction commodities. The matching **System** column shows which star system that station is in, so you can plot a route without bookmarking every station by name.
- The **Distance** column shows how far that preferred market is from the construction site, in light years.
- In the **-All-** view Distance is left blank (there is no single site to measure from).
- Click any column header to sort the list. Click **Shortfall** to put the biggest remaining buys first (click again to reverse).
- **Ctrl+click** or **Shift+click** a row to copy that System name to the clipboard (handy for the galaxy map search box). The Preferred Market label briefly shows `Copied: …` as confirmation.
- Markets can be filtered using the $\Ly\Alt and O\S buttons at the top of the inteface. Filtering includes:
  - $ : the station that has the cheapest sell price that was below your construction sites buy price.
  - Ly : the station that is closest to your colony system whose sell price was below your construction sites buy price.
  - Alt : the station that is closest to your colony system whose sell price was NOT below your construction sites buy price.
  - O : orbital stations are shown. If none have been found, a surface settlement is shown with an asterix (*) prepended to the name. Otherwise it will be blank.
  - S : surface settlement are shown. If none have been found, an orbital station is shown with an asterix (*) prepended to the name. Otherwise it will be blank.
- Note: if you started using this plugin prior to version 1.4, the old data will be shown with a double asterix (**) prepended to the name untill you have landed at the market again.

### Fleet Carrier Cargo Quantities
- Information coming from the fleet carrier CAPI (fcapi) queries can often become unsyncronized with the actual amounts shown in the game. This causes Architect Tracker to sometimes display incorrect fleet carrier cargo quantities. As a work around, I have added a pause\unpause button next to the carrier name.
- Transferring cargo to\from your starship or buying\selling commodities at your own fleet carrier's market are still tracked by Architect Tracker regardless.
- The pause\unpause button has 2 modes it can operate which can be set in the "Settings" of EDMC:
  - "First then pause" mode will accept the first fcapi query then ignore any others unless the pause button is clicked. This is the default mode. I have found that the first query is usually accurate if I haven't played for over an hour.
  - "Only when UNpaused" mode will accept all fcapi queries unless you pause them.
- Note: if you sell commodities to other players from your fleet carrier, pausing fcapi queries will cause the fleet carrier cargo amounts in Architect Tracker to become out of sync. Unpausing will, hopefully, restore them.

### Notes
1. VR programs like Desktop+ can display this window inside the game for you.
2. For Voice Attack users:
  - The "<", ">" buttons are bound to the keys "<", ">" respectiveley.
  - The "$\Ly\Alt" button is bound to key "p".
  - The "O\S" button is bound to key "o".
  - The pause\unpause button is bound to "u".
  - Also "t" has been bound to the Architect Tracker button on the EDMC window so you can show\hide the Architect Tracker interface to stop tracking.
  - These keys are ignored while you are typing in a text box, so renaming a column in the settings tab or filtering the log viewer will not trigger them.
3. Linux: the plugin uses the journal folder EDMC is already watching. If EDMC has found your journals then so has the plugin, whether Elite is installed under Steam, Flatpak Steam, Snap Steam or on a second drive. If neither can find them, set the folder in EDMC's File > Settings > Configuration tab.
4. Running the tests (only needed if you are changing the code): `python3 tests/test_plugin.py`, or `xvfb-run -a python3 tests/test_plugin.py` on a machine with no display. EDMC does not need to be installed.

### Notable Changes
+ 2025/04/12 : Added support for multiple construction sites. Sites are removed automaticly when they are completed.
+ 2025/04/19 : Added feature - commodities required for construction are highlighted when a commodity market is opened.
+ 2025/04/25 : Added fleet carrier cargo information - open the carrier management tool in-game to populate\refresh this list. NOTE: Tracks cargo transfers to/from FC but not market sales.
+ 2025/04/30 : Added starship cargo tracking and dark theme colours.
+ 2025/05/01 : Deleted unworking style , ad setings for beter use
+ 2025/05/03 : Adaptation for new naming conwention for colonisation ship
+ 2025/05/06 : Added dark\light mode, moved setting to EDMC setting tab, setting saved to EDMC settings and window auto resized to fit content.
+ 2025/05/09 : Added delete station button to remove unwanted stations, added next station button to change list to next station in list (using Desktop+ in VR doesn't show the dropdown menu also button has a hot key assigned to it ">" so it can be used by voice attack), added alternating row colours back in.
+ 2025/05/15 : Added preferred market tracking, added row highlighting, added information to settings tab and added column header renaming.
+ 2025/05/29 : Added pause to tracking. Closing the Architect Tracker window will stop the commodities from being tracked.
+ 2025/06/29 : [version 1.0] Added features - can now adjust transparent background, window opacity and stay on top of the main gui in the settings menu. Also added a verion number for bug reporting.
+ 2025/08/05 : [version 1.1] Added feature - Selecting -All- in the station dropdown list will display materials from all construction sites in a single view.
+ 2025/11/03 : [Version 1.2] Added previous site button to UI, owned fleet carrier no longer registers as market, remove version number from window title and improved start up to detect if landed on a market or carrier.
+ 2026/02/12 : [Version 1.2.2] Fixed bug that prevented Material column from displaying for some users.
+ 2026/02/23 : [Version 1.3] Added pause button for fleet carrier cargo, added totals row at bottom of list, delete site button is disabled when ALL sites are shown, smaller bug fixes.
+ 2026/03/20 : [Version 1.4] Added alternate and orbital\surface filtering to preferred markets. Renamed construction sites and markets will now be updated when you land on them the next time. Minor UI beautifications.
+ 2026/04/04 : [Version 1.5] Changed highlight rules when on fleet carrier. Now, if you have enough of a commodity on your starship to meet the needs of the construction site, the commodity will no longer be highlighted.
+ Added : Import market data for markets you have not visited, from spansh.co.uk. Set a search radius and whether you want orbital or surface markets in the settings tab. Prices are now recorded as what you pay for a commodity rather than what the market would pay you for it.
+ 2026/06/11 : [Version 1.6] Major bug fixes for Linux users. Special thanks to Commanders PatientNr0, mgrzegor, Fasgort and LiamtheLion879
 for taking time to report bugs and work with me to fix them. Added log viewer to settings tab which should helppeople report bugs.
+ 2026/08/06 : [Version 2.0] Fork release with Linux journal discovery (Steam/Proton/Flatpak/Snap), crash fixes when the tracker window is closed, BuyPrice preferred-market tracking, Spansh nearby-market import, settings persistence with the window closed, and a fix so the EDMC settings tab no longer vanishes when opening Architect Tracker preferences.
+ 2026/08/07 : [Version 2.1] Added a System column next to Pref Market, an L / L&M landing-pad filter on the Spansh import panel, and Ctrl+click / Shift+click to copy a system name to the clipboard.
+ 2026/08/09 : [Version 2.2] Sortable commodity columns (click Shortfall for biggest buys first), Distance (ly) to the preferred market, slightly larger tracker font, plus a bug scrub for site Location sync, station name matching, Cheap/Closest demotion, and split cargo stacks.
+ 2026/08/10 : [Version 2.3] Optional in-game shortfall list via EDMC Overlay / Overlay2 / Modern Overlay — left side of the game, from mid-screen downward.
+ 2026/08/13 : [Version 2.5] Overlay position dropdown (top / mid / bottomish left). Fleet carrier cargo no longer snaps back when a stale CAPI snapshot arrives after a transfer to ship; ship and carrier columns use the same commodity spelling. Releases are now **ArchitectTracker_enhanced.zip** (stable plugin folder name, no version in the zip).
