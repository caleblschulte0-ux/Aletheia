# Instagram auto-posting: where the Meta door actually is (2026-10-01)

Posting account: **@lieutenantmemestrong** (Business portfolio
"Lieutenantmemestrong"). Personal account **@caleb_schulte_1** is
`NEVER_TOUCH` in `aletheia/instagram.py` and is not part of any of this.

## What is really blocking it

Read off the 2026-09-25 screens (session "Aletheia Instagram auto-post"):

- Business settings -> Apps -> Create a new app ID said *"Your account must
  be confirmed before you can create a new app. Please confirm your account
  by adding your mobile phone number or credit card."*
- developers.facebook.com/apps/creation/ did not open the app form. It
  redirected to **"Create a Meta for Developers account" -> Register ->
  Contact info -> "Enter the Code from Your Email"**, sent to
  ballerbro2.01818@gmail.com. That dialog was never completed.
- The only "contact with Meta" so far was the **Meta AI business
  assistant** chat titled "Confirm Account For App Creation". Business
  Support Home showed **"No support cases"**. No human at Meta has seen
  this.
- facebook.com/confirmphone.php returned Facebook's generic error page.

So the Facebook account has **no developer registration**, and the
registration is what will not finish. Meta's own developer forum has the
same report from many people in September 2026 (SMS code never arrives,
or the dialog loops back to Contact info after Complete Registration),
with no reply from Meta on any of them. It is not a device problem and
not an Instagram problem. Retrying the same thing on the same device will
not change it.

## Three ways through, in the order to try them

1. **Finish the registration, differently.** On the phone, over mobile
   data (not home wifi), VPN off: developers.facebook.com/async/registration/
   -> **Update Email** to an inbox you actually read -> enter the email
   code -> phone code -> pick a role -> Complete Registration.
2. **If it loops or no SMS ever comes:** Accounts Center -> Payments ->
   add a payment method. PayPal is accepted and nothing is charged. People
   with this exact error report the "account must be confirmed" gate
   clearing after that. Then retry 1.
3. **Borrow a developer account.** Anyone who already has a Meta developer
   account can own the app. They create it (use case Other, type Business,
   add "Manage everything on your Instagram account"), add
   `lieutenantmemestrong` under **App roles -> Roles -> Instagram testers**;
   you accept in Instagram (Settings -> Website permissions / Apps and
   websites -> Tester invites); then **Generate token** for that account in
   their dashboard works, with Standard Access, no app review.

Any of the three ends the same way: paste the token into
`python -m aletheia.instagram connect`. The API route takes over on its
own from that moment.

## Reaching a human at Meta

There is no inbound email or phone. The two real channels:

- **Business Support Home** (business.facebook.com/business-support-home,
  on a desktop, signed in): *Get support / Contact support team* -> choose
  the Lieutenantmemestrong portfolio -> chat or email. This opens a CASE
  with a person, which the Meta AI chat did not. Message to paste:

  > My Facebook account cannot complete Meta for Developers registration.
  > developers.facebook.com/async/registration/ sends an email code and then
  > loops back to Contact info / never delivers the SMS code, so I cannot
  > create an app ID: Business settings says "Your account must be confirmed
  > before you can create a new app." A mobile number is already confirmed on
  > the account and two-factor authentication is on. This happens on every
  > device and network. Please reset or manually complete the developer
  > registration on this account, or tell me the exact verification step
  > that is failing. I need the app only to publish to my own Instagram
  > professional account @lieutenantmemestrong with the Instagram API with
  > Instagram Login (instagram_business_basic,
  > instagram_business_content_publish).

- **developers.facebook.com/support** -> *Contact Direct Support*, which
  only works once a developer account exists (that is why the bug tool
  refused on 2026-09-25).
