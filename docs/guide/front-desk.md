# YTKTV Desk: running several rooms

YTKTV Desk is the front desk for a home or a shop with more than one karaoke room. One
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

1. Install **YTKTV Desk** on the front-desk computer: `YTKTV-Desk-<version>-…` from the
   [latest release](https://github.com/TonyD365/YTKTV/releases/latest) (on macOS, run
   `xattr -d com.apple.quarantine` on the package first, as for YTKTV).
2. Every room needs YTKTV on the same network (Wi-Fi or cable).
3. On the Desk, press **＋ Add Room**. It shows a 6-digit code (good for 5 minutes, once) and a
   **security code** of four pictures.
4. On the room's YTKTV open **Settings → Front Desk**, press **Find Desks** and pick the desk
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
points per unit spent in **Settings → Menu and prices**.

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
- **Room types** (Small, Medium, Large, VIP, Party) with seats, and a price per hour for each
  room if they differ: **Settings → Room settings**.
- **Menu and stock**: items with a category, price and stock (empty means it never runs out).
  Sold-out items leave the menu by themselves.

## Records and shift reports

Every check-out is kept in **Records** with its bill and the songs sung; pick a day to see its
sessions, hours, takings and most-sung songs. The top bar shows today's takings.

**📋 Shift Report** adds up everything since the last hand-over: sessions, room fees, items,
takings by payment method, items sold and rooms still open. Print it, then **Hand Over** to start
the next shift.

## Settings and the desk password

**Settings → Desk password** turns on a password that is asked when the Desk starts, after it
has been idle (5, 15 or 30 minutes, or never), and before a room is unbound.

YTKTV Desk updates itself like YTKTV: when a new version is out, **⬆ Update to …** appears in the
top bar.

## Questions

**Does the Desk need the internet?** Only for updates. Rooms and the Desk talk over your own
network. YTKTV in the rooms needs the internet for YouTube.

**What if the Desk is off?** Open rooms keep singing and counting down; their calls and orders
are sent when the Desk is back. Closed rooms stay closed.

**Can the Desk computer also be a room?** Run YTKTV Desk on its own computer; any other computer
can be a room.
