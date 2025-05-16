# EliteDangerous

## Architect Tracker
Displays commodities required, provided and needed when you land at a construction site and tracks cargo in your fleet carrier and starship.
The focus is to create a simple to use and hands free tracker for system colonisation. I will be adding features often so check back here often. This was created using ChatGPT. It probably took me as long to create as a human could have programmed manually but I have no experience programming in Python or for the EDMC so it is kind of impressive.

![Screenshot 2025-05-15 162848](https://github.com/user-attachments/assets/c1d6b250-bd17-4492-96a2-94b1d59fb954)

Dark mode

![Screenshot 2025-05-15 184939](https://github.com/user-attachments/assets/4f9beacd-d875-4708-ab02-ac642c7f2d05)

Light Mode

![Screenshot 2025-05-15 183805](https://github.com/user-attachments/assets/17a1b392-6c6b-43a6-9c07-ba6fb5deeeca)

Settings Window

### Discussion
https://forums.frontier.co.uk/threads/colonization-tool-architect-tracker.636854/#post-10621804

### Install Instructions
1. Create a directory called "Architect Tracker" in the the ED: Marketplace Connector plugins folder.
2. Save the code from "Architect Tracker.py" into a file called "load.py".
3. Start EDMC.

### Usage
+ When you land at a construction site the plugin will (after a few moments) list all the commodities and amounts required, provided and needed. You can switch between sites from the dropdown list in the upper left or the ">" button. The window will resize itself to fit all the commodities.
+ The "Pref Market" column displays either the cheapest and closest market where that commidity has been found. The "$\Ly" button toggles between cheapest and closest martket.
+ To display\update your fleet carrier cargo, open the "Carrier Management" in-game tool. The quantities will appear after a few moments (this can take a while and occasionaly display incorrect number). If you are also selling commodities from your fleet carrier, you will need to update this list as needed (sales are not tracked).
+ Starship cargo will be displayed automatically.
+ The shortfall column displays how much of a commodity you still need to aquire.
+ Settings are available in the E:D Market Connector under File menu->Settings->ArchitectTracker tab. You can choose whioch columns to display, set the text displayed in the column header and other settings (see screenshot above).
+ Rows are highlighted (see screenshots above) depending on where you are docked, rows are highlighted to indicate:
  + Markets - market is selling the item and you have shortfall.
  + Fleeet Carrier - site needs it and fleet carrier has some.
  + Construction site - site needs it and starship has some.

### Notes
1. VR programs like Desktop+ can display this window inside the game for you. The ">" and "$\Ly" buttons are bound to the keys ">" and "p" respectively for Voice Attack users.

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
