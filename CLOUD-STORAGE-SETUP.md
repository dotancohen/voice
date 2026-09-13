# Setting up cloud storage for your recordings

**There is a wizard now.** On the desktop, File → Set up the bucket… (or
`python -m src.main cli storage setup`) does every Amazon step below for you,
one screen at a time, and tests the result. This guide stays for
DigitalOcean and Backblaze, and for reading what the wizard does.

This guide is for someone who has never done this before. It assumes only that
you can use a web browser, and that you have an account with a credit card on it.

You do not need to understand any of it to follow it. Where a step needs a
decision, the answer is given.

Read [What this is for](#what-this-is-for) and [What it costs](#what-it-costs),
then do **one** of:

- [Amazon S3](#amazon-s3) — the original, cheap for small amounts, the most
  fiddly to set up
- [DigitalOcean Spaces](#digitalocean-spaces) — one flat price, the simplest
  screens
- [Backblaze B2](#backblaze-b2) — the cheapest for large amounts

Then [type the five values into Voice](#telling-voice-about-it) and
[check it worked](#checking-it-worked).

**Which ones work today:** Amazon S3 is in daily use. DigitalOcean Spaces and
Backblaze B2 speak the same language as Amazon S3, and Voice can already be
pointed at them, but nobody has run them in earnest yet — if you pick one of
those, expect to report a problem or two.

---

## What this is for

A recording lives on the device that made it. If you record on your phone, the
sound file is on your phone and nowhere else.

Cloud storage gives every recording a second home:

- Your other devices can fetch a recording they do not have, when you ask to play
  it.
- If your phone is lost, stolen, dropped in water, or wiped, the recordings are
  still there.

**It is not a complete backup by itself.** Your notes, tags and transcriptions
travel between your devices through your own sync server; cloud storage holds the
sound files only. You want both. And if you want a full copy of every recording
on your computer as well, there is a setting for that — see the end of this
guide.

Nobody but you can read any of it. The files go over an encrypted connection, the
bucket is private, and only the key you are about to create can open it.

---

## What it costs

Recordings are small. Speech at the quality Voice records is roughly **1 MB per
two minutes**, so an hour of recording is about 30 MB, and a year of heavy daily
use might be 10–20 GB.

Approximate monthly cost for 20 GB stored — **check the current price on each
service's own pricing page, because these change**:

| Service | Storage | 20 GB costs about | Downloading it all once |
|---|---|---|---|
| Amazon S3 | $0.023 per GB | **$0.46** | about $1.80 after the first 100 GB each month, which is free |
| DigitalOcean Spaces | $5 flat, includes 250 GB | **$5.00** | included, up to 1 TB a month |
| Backblaze B2 | $0.006 per GB | **$0.12** | free up to three times what you store |

For 20 GB, Amazon and Backblaze cost less than a cup of coffee a year.
DigitalOcean costs more at this size but never surprises you. All three also
charge tiny amounts per request; for one person's recordings this is pennies.

**Set a spending alert.** Whichever you choose, find *Billing* in its menu and
set an email alert at a figure that would worry you — $5, say. This protects you
against a mistake of your own making, not against the service.

---

## The five things you are collecting

Every service gives you the same five pieces of information. Keep them in a
password manager or a note you trust until you have typed them into Voice.

| Name | What it looks like | What it is |
|---|---|---|
| **Bucket name** | `dotan-voice-recordings` | The name of the container your files go in. You choose it |
| **Region** | `us-east-1`, `nyc3`, `us-west-004` | Which part of the world it lives in |
| **Access key ID** | `AKIAIOSFODNN7EXAMPLE` | The username of a key, about 20 characters |
| **Secret access key** | `wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY` | The password of that key, about 40 characters |
| **Endpoint** | `https://nyc3.digitaloceanspaces.com` | The address of the service. **Amazon only: leave this empty** |

The secret access key is a password. It is shown **once**, when you create it. If
you close that screen without copying it, you cannot get it back — you delete
that key and make another. Nobody can recover it for you.

---

## Amazon S3

You need an amazon.com account with billing set up, which you have. The storage
lives in Amazon Web Services, which uses the same sign-in.

### 1. Sign in

1. Go to **https://console.aws.amazon.com**
2. Sign in. If you are asked "Root user" or "IAM user", choose **Root user** and
   use your ordinary amazon.com email and password.
3. If it asks to set up multi-factor authentication, do it. It takes two minutes
   and it protects everything below.

### 2. Make the bucket

1. At the top of the page there is a search box. Type **S3** and press Enter,
   then click **S3** in the results.
2. Click the orange **Create bucket** button.
3. **AWS Region**: open the list and choose the one nearest to you. Write down
   the code in brackets — it looks like `eu-central-1` or `us-east-1`. **This is
   your Region.**
4. **Bucket name**: type a name. The rules: lower-case letters, numbers and
   hyphens only, at least 3 characters, and it must be unlike every other bucket
   name in the world. So put something of your own in it:
   `dotan-voice-recordings-7214`. **This is your Bucket name.**
   - If it says the name is taken, add more numbers to the end.
5. Leave everything else exactly as it is. In particular **Block all public
   access** must stay ticked — that is what keeps your recordings private.
6. Scroll to the bottom and click **Create bucket**.

### 3. Make a key that can only touch that bucket

Do not use your main account password for this. You are making a narrow key that
can open this one bucket and nothing else, so that it can do no harm if it leaks.

1. In the search box at the top, type **IAM** and press Enter, then click **IAM**.
2. On the left, click **Users**. Click **Create user**.
3. **User name**: `voice-app`. Click **Next**.
4. On the permissions page, choose **Attach policies directly**, then click
   **Create policy**. A new tab opens.
5. In the new tab, click the **JSON** tab. Delete everything in the box and paste
   this in, then **replace both copies of `YOUR-BUCKET-NAME`** with the bucket
   name from step 2.4:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:ListBucket"],
      "Resource": "arn:aws:s3:::YOUR-BUCKET-NAME"
    },
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
      "Resource": "arn:aws:s3:::YOUR-BUCKET-NAME/*"
    }
  ]
}
```

6. Click **Next**. **Policy name**: `voice-recordings`. Click **Create policy**.
7. Close that tab and go back to the tab where you were creating the user. Click
   the refresh arrow next to the list of policies, type `voice-recordings` in the
   search box, and tick it.
8. Click **Next**, then **Create user**.

### 4. Get the two halves of the key

1. Click the user **voice-app** in the list.
2. Click the **Security credentials** tab.
3. Scroll to **Access keys** and click **Create access key**.
4. It asks what it is for. Choose **Other**, click **Next**, then **Create access
   key**.
5. You are now on the only screen that will ever show you the secret.
   - **Access key** is your **Access key ID**.
   - **Secret access key** — click **Show** — is your **Secret access key**.
   - Copy both into your password manager now. Or click **Download .csv file**
     and keep the file somewhere safe.
6. Click **Done**.

You have all five values. **Endpoint is left empty for Amazon.** Go to
[Telling Voice about it](#telling-voice-about-it).

---

## DigitalOcean Spaces

You need a DigitalOcean account with a card on it: **https://cloud.digitalocean.com**

### 1. Make the Space

1. Sign in. In the left-hand menu click **Spaces Object Storage**.
2. Click **Create Spaces Bucket**.
3. **Choose a datacenter region**: pick the nearest. Note the short code under
   the city name — `nyc3`, `ams3`, `fra1`, `sgp1`. **This is your Region.**
4. **Enable CDN**: leave it off. You do not need it and it costs more.
5. **Choose a unique name**: `dotan-voice-recordings`. Lower-case letters,
   numbers and hyphens. **This is your Bucket name.**
6. Click **Create a Spaces Bucket**.

Your **Endpoint** is `https://` followed by your region code and
`.digitaloceanspaces.com` — for region `nyc3` that is
`https://nyc3.digitaloceanspaces.com`.

### 2. Make the key

DigitalOcean has two kinds of key and only one of them works here. You want a
**Spaces key**, not an API token.

1. In the left-hand menu, at the bottom, click **API**.
2. Click the **Spaces Keys** tab. (If you are on **Tokens**, you are in the wrong
   place.)
3. Click **Generate New Key**.
4. **Name**: `voice-app`. If it offers a scope, limit it to the bucket you just
   made. Press Enter or click the tick.
5. Two long strings appear:
   - the first is your **Access key ID**
   - the second, shown only now, is your **Secret access key**
6. Copy both into your password manager before you leave the page.

Go to [Telling Voice about it](#telling-voice-about-it).

---

## Backblaze B2

You need a Backblaze account with billing set up:
**https://www.backblaze.com/sign-in.html**

Backblaze uses different words for the same things. The translation is at the end
of this section.

### 1. Make the bucket

1. Sign in. In the left-hand menu, under **B2 Cloud Storage**, click **Buckets**.
2. Click **Create a Bucket**.
3. **Bucket Unique Name**: `dotan-voice-recordings-7214`. It must be unlike every
   other Backblaze bucket name in the world, so include something of your own.
   **This is your Bucket name.**
4. **Files in Bucket are**: choose **Private**. This matters.
5. Leave encryption and object lock alone. Click **Create a Bucket**.

### 2. Find the endpoint and the region

1. Back on the **Buckets** page, look at your new bucket. Under its name is a
   line reading **Endpoint: s3.us-west-004.backblazeb2.com** or similar.
2. Your **Endpoint** is that, with `https://` in front:
   `https://s3.us-west-004.backblazeb2.com`
3. Your **Region** is the middle part of it: `us-west-004`.

### 3. Make the key

1. In the left-hand menu click **Application Keys**.
2. Click **Add a New Application Key**.
3. **Name of Key**: `voice-app`.
4. **Allow access to Bucket(s)**: choose your bucket, not "All".
5. **Type of Access**: **Read and Write**.
6. Leave the rest empty. Click **Create New Key**.
7. The next screen shows, once only:
   - **keyID** — this is your **Access key ID**
   - **applicationKey** — this is your **Secret access key**
8. Copy both into your password manager before you leave the page.

**The translation:**

| Backblaze calls it | Voice calls it |
|---|---|
| keyID | Access key ID |
| applicationKey | Secret access key |
| Endpoint (on the bucket) | Endpoint |
| The middle of the endpoint | Region |

---

## Telling Voice about it

Do this **once**, on your computer. The setting travels to your phone and your
other computers the next time they sync, so you do not have to type it again
anywhere.

Open a terminal in the Voice folder and type this as one command, putting your
own five values in. Keep the quotation marks.

**For Amazon S3** (no endpoint):

```bash
.venv/bin/python -m src.main cli storage configure-s3 \
    --bucket "dotan-voice-recordings-7214" \
    --region "eu-central-1" \
    --access-key-id "AKIAIOSFODNN7EXAMPLE" \
    --secret-access-key "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
```

**For DigitalOcean Spaces or Backblaze B2** (the endpoint line is the difference):

```bash
.venv/bin/python -m src.main cli storage configure-s3 \
    --bucket "dotan-voice-recordings" \
    --region "nyc3" \
    --access-key-id "DO00EXAMPLEKEY123456" \
    --secret-access-key "examplesecretkeyexamplesecretkeyexample" \
    --endpoint "https://nyc3.digitaloceanspaces.com"
```

If a value of yours contains a character the terminal dislikes, the quotation
marks already handle it. Secret keys often contain `/` and `+`; that is normal.

---

## Checking it worked

```bash
# What Voice thinks it is configured with. The secret is not shown back to you.
.venv/bin/python -m src.main cli storage status

# Send every recording on this computer that is not in the bucket yet
.venv/bin/python -m src.main cli storage upload-pending
```

Then look in the service's own web page — the bucket should have files in it,
named like `01a0952602bc7080.opus`. That is the proof.

On your phone: Settings → Sync Settings → sync once, and a note whose recording
is not on the phone will offer a **Download** button where it used to say the
recording was elsewhere.

If it fails, the error says which of the five values the service rejected.
The usual causes, in order of likelihood: a space accidentally copied onto the end
of a key; the wrong region; an endpoint without `https://` in front; or a
DigitalOcean API token used instead of a Spaces key.

---

## Keeping it safe

- **The secret access key is a password.** Do not put it in an email, a chat
  message, or a screenshot.
- **If it ever leaks**, delete that key in the service's web page and make a new
  one, then run the `configure-s3` command again with the new values. Nothing is
  lost: the recordings stay where they are.
- The key you made can only read and write this one bucket. It cannot spend money
  elsewhere in your account, start servers, or see anything else you keep there.
- Keep the spending alert from [What it costs](#what-it-costs) switched on.

---

## One more thing worth doing

Cloud storage protects you against losing a device. A copy on your own computer
protects you against losing the *account*, and it costs nothing. One command, on
the computer:

```bash
.venv/bin/python -m src.main cli storage mirror enable
```

Every sync then downloads any recording the computer does not have, so the
computer ends up holding all of them. `storage mirror disable` undoes it. Do not
do this on your phone, which does not have the room.

If your recordings matter to you, do this **as well as** the bucket, not instead
of it. A copy in one place is not a copy.
