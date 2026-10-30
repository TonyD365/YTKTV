# YTKTV Desk: running several rooms

YTKTV Desk is the staff terminal for a home or a shop with more than one karaoke room. One
computer runs the Desk; every room's computer runs YTKTV and is bound to it. From the Desk
you open and close rooms, time them, take service calls and orders, bill, book, and keep the
day's records.

- [Install and pair](#install-and-pair)
- [Open, extend and close a room](#open-extend-and-close-a-room)
- [Service calls and orders](#service-calls-and-orders)
- [Checking out: the till](#checking-out-the-till)
- [Members](#members)
- [Receipts](#receipts)
- [Bookings](#bookings)
- [Running the floor](#running-the-floor)
- [Records and shift reports](#records-and-shift-reports)
- [Settings and the desk password](#settings-and-the-desk-password)
- [Questions](#questions)

## Install and pair

1. Install **YTKTV Desk** on the staff computer: `YTKTV-Desk-<version>-…` from the
   [latest release](https://github.com/TonyD365/YTKTV/releases/latest) (on macOS, run
   `xattr -d com.apple.quarantine` on the package first, as for YTKTV).
2. Every room needs YTKTV on the same network (Wi-Fi or cable).
3. On the Desk, press **＋ Add Room**. It shows a 6-digit code (good for 5 minutes, once) and a
   **security code** of four pictures.
4. On the room's YTKTV open **Settings → Staff Terminal**, press **Find Desks** and pick the desk
   (or type the address the Desk shows, such as `192.168.1.10:8770`), enter the code and a room
   name, press **Bind**.
5. YTKTV shows four pictures. Press **Yes** only if they are the same as on the Desk.

The room now shows **This room is closed** until the Desk opens it.

**A binding is permanent.** A room cannot unbind itself unless the Desk has been offline for 7
days, and even then someone has to press **Unbind** in its settings. The Desk can unbind a room
at any time in **Settings → Room settings**. Rooms find the Desk by its ID, so a new IP address
for the Desk does not matter, and they only obey messages the Desk has signed.

## Open, extend and close a room

Pick a room on the board, then in the sidebar:

- **🔑 Open Room**: a guest name (optional) and 1, 2 or 3 hours, or no time limit. YTKTV in that
  room unlocks; the console and the TV show the time left, with a warning at 10 minutes.
- **⏱ Extend Time**: 30 minutes or an hour more. A room whose time ran out gets it from now.
- **🔁 Change Room**: moves the party, with its time, orders and songs, to a free, clean room.
- **💳 Check Out**: the bill (see below); then the room closes and its queue is cleared.

When time is up, the song that is playing finishes, the TV says **Time's up**, and the room
closes. The Desk keeps the tile red until you check it out.

The room board uses colours: free, booked, in use, ending soon, time's up, calling, cleaning,
maintenance and offline, with the count of each at the top. Tiles show the guest, the time left,
what the room has spent so far and the song it is singing.

## Service calls and orders

Guests press **🛎 Service** on the console, or use the service buttons on their phones, to ask
for drinks, snacks, help with the equipment or anything else, or to order from the menu. The
Desk beeps, the room's tile turns pink and the call appears in the bar at the bottom. Click it
when someone is on the way: the room is told **Staff is on the way**.

When a product on the menu runs low, it shows in the same bar ("📦 Cola: 2 left", or "sold
out"). Click it to go to Settings and restock. **Settings → Shop → Warn when stock is down to**
sets the number (5 at first; 0 turns the warnings off).

Orders appear in the room's panel. Mark them **Delivered** or **Cancel** them (cancelled items go
back into stock). **🛒 Add Item** adds something the guests ordered at the counter.

## Checking out: the till

**💳 Check Out** opens the bill:

- **Member**: type the member's phone number and press **Find**. Members save the set percent
  and earn points.
- **Discount**: any percent off.
- **Drop small change**: to a whole number, or to the ten below.
- **Paid by**: cash, card, WeChat Pay, Alipay or the member's balance (refused when it is not
  enough).

**Print…** and **Save PDF…** give a full-page bill; **🧾 Receipt** prints a receipt. **Close Room**
takes the payment, closes the room and turns it to **Cleaning**.

Rooms are charged per hour: for the booked time when the room has a limit, or for the time used,
rounded as set (by the minute, every started hour, or every started block), when it has none.
A minimum spend can apply.

## Members

The **Members** tab lists members with their stored balance and points. **＋ New Member** needs a
name and a phone number; **💰 Top Up** adds to the balance. Set the members' discount and the
points per unit spent in **Settings → Menu and prices**. **🎂 Birthday** saves a member's
birthday (MM-DD): on that day they also get the birthday discount set in **Settings → Packages
and coupons**.

## Packages and coupons

**Settings → Packages and coupons**:

- **Packages** sell room time and items at one price, for example *Party, 3 hours, 1 × Beer
  tower, $99*. When you open a room, the packages are offered under **How long?**. The bill
  charges the package; time beyond it is charged by the hour. Hand the included items over
  yourself (they are printed on the bill).
- **Coupons** take a percent or an amount off a bill. Each has a code, an optional number of uses
  and an optional last day. At the till type the code under **Coupon** and press **Apply**; the
  bill shows it, and a use is counted when the room closes.
- **Members' birthday discount**: an extra percent off for a member on their birthday.

## Receipts

Any 58 mm or 80 mm receipt printer that is installed on the Desk computer works, through its
driver. In **Settings → Receipts** choose the printer (or "Ask each time"), the paper width, the
shop's name, a closing line, the number of copies, and whether to print a receipt at every
check-out. Set the printer's driver to cut the paper after each receipt if it can.

## Bookings

The **Bookings** tab has a calendar, a timeline of every room's day and the list of bookings.
**＋ New Booking** takes a room, a time, a length, the guest's name and contact and a note; it
warns when the room is already booked then. Tiles show the next booking, and the Desk beeps 15
minutes before a guest is due. When they arrive, select the booking and press **Check In**: the
room opens as booked. Or mark it **Cancelled** or **No-show**.

## Running the floor

- **Cleaning and maintenance**: a checked-out room shows **Cleaning** until you press **🧹 Cleaned**;
  **🔧 Maintenance** takes a room out of use.
- **Remote control** in the room's panel: skip, pause, music volume, a message, or lock the room
  for a moment (its queue and time are kept).
- **📢 Broadcast**: a message to every open room, or some of them, for 10 or 30 seconds or until
  someone presses **Got it**, optionally pausing the music with a sound.
- **Local songs only** (**Settings → Room settings**): the room may sing only video files from its
  own computer's local folders, not YouTube. An open room changes at once.
- **Room types** (Small, Medium, Large, VIP, Party) with seats, and a price per hour for each
  room if they differ: **Settings → Room settings**.
- **Menu and stock**: items with a category, price and stock (empty means it never runs out).
  Sold-out items leave the menu by themselves.

## Records and shift reports

Every check-out is kept in **Records** with its bill and the songs sung. Choose **Day**, **Week**
or **Month** and a date to see the sessions, hours, takings and most-sung songs, with a bar chart
of the takings per hour (for a day) or per day. **Export CSV** saves every session in that period
as a spreadsheet that Excel opens, names in any language included. The top bar shows today's
takings.

**📈 Insights** shows the last 7, 30 or 90 days at a glance: takings, sessions, spend per session
and hours sung; the busy hours of the day and the takings per weekday as charts; and the top
songs, best-selling items, takings per room and how guests paid.

**📋 Shift Report** adds up everything since the last hand-over: sessions, room fees, items,
takings by payment method, items sold and rooms still open. Print it, then **Hand Over** to start
the next shift.

## Several staff terminals

One Desk keeps the records (the main Desk); other computers running YTKTV Desk can work on it as
**staff terminals**, at the bar or upstairs, and see the same rooms, bookings, members and records.

1. On the main Desk open **Settings → Staff Terminals**, give it a name (it is shown in the log),
   tick **Let other Desks connect as staff terminals** and press **Add Terminal**. A six-digit
   code and four pictures appear.
2. On the other computer open YTKTV Desk → **Settings → Staff Terminals → Make This Desk a Staff
   Terminal…**, pick the main Desk (or type its address), enter the code and a name for this
   terminal, and press **Connect**. Check that the four pictures match the main Desk's, then
   open YTKTV Desk again.

A terminal keeps nothing of its own: everything it does happens on the main Desk. If the main
Desk cannot be reached, the terminal says so at the top and tries again on its own. **Remove**
on the main Desk, or **Disconnect** on the terminal, ends the pairing.

**On a phone**: Settings → Staff Terminals shows a link and a QR code (`https://<desk address>/staff`).
Open it on a phone on the same Wi-Fi, accept the browser's security warning once (the Desk's
certificate is its own, not from a public authority), then enter a code from **Add Terminal**
and your name. The phone shows the rooms (open with a guest and a length, +30 / +60 minutes,
check out with the payment method at the usual prices, mark cleaned), the service calls (**On my
way**) and the orders waiting (**Delivered** or **Cancel**). Discounts and members stay on the
Desk's till.

**📜 Log** lists everything done on the main Desk and its terminals by day: the time, the
machine's name and what was done ("Bar: Closed Kids, $60.00 by Card"). Choose a machine to see
only its actions. Passwords are never written into the log.

## Settings and the desk password

**Settings → Desk password** turns on a password that is asked when the Desk starts, after it
has been idle (5, 15 or 30 minutes, or never), and before a room is unbound.

YTKTV Desk updates itself like YTKTV: it checks every six hours, downloads a new version in the
background, and shows **⬆ Update to …** in the top bar; nothing installs until you press it.
**Settings → Updates** shows the version, turns the automatic checks off or on, and has
**Check Now**.

## Questions

**Does the Desk need the internet?** Only for updates. Rooms and the Desk talk over your own
network. YTKTV in the rooms needs the internet for YouTube.

**What if the Desk is off?** Open rooms keep singing and counting down; their calls and orders
are sent when the Desk is back. Closed rooms stay closed.

**Can the Desk computer also be a room?** Run YTKTV Desk on its own computer; any other computer
can be a room.
