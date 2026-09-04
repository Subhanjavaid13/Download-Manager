import type { Metadata } from "next";

import { Fill, LegalHeading, LegalPage } from "@/components/legal";

export const metadata: Metadata = {
  title: "Privacy Policy · Downloader Manager",
  description: "Exactly what this app stores, for how long, and how to delete it.",
};

export default function PrivacyPage() {
  return (
    <LegalPage
      title="Privacy Policy"
      intro="What is stored, for how long, and how to get rid of it."
    >
      <p>
        This app is run by <Fill>OPERATOR NAME</Fill>, who decides what happens to the data below
        and can be reached at <Fill>CONTACT EMAIL</Fill>. It stores as little as it can while still
        working, and none of it is sold or shared for advertising.
      </p>

      <LegalHeading>The files you download</LegalHeading>
      <p>
        A finished file lives on the server for one hour and is then deleted by a scheduled job. The
        download link stops working at the same moment. Nobody browses these files, and they are not
        listed anywhere public. Partly downloaded files are deleted as soon as a download fails or
        is cancelled.
      </p>

      <LegalHeading>Your download history</LegalHeading>
      <p>For each download, one database row records:</p>
      <ul>
        <li>
          the YouTube <em>video id</em> only, never the full address you pasted, so tracking
          parameters and playlist positions are dropped before anything is written down;
        </li>
        <li>the title, channel, length, and thumbnail address YouTube reported;</li>
        <li>
          what you asked for and what came out: audio or video, format, quality, file size, whether
          it worked, and the error if it did not;
        </li>
        <li>when it started and finished.</li>
      </ul>
      <p>
        The row stays after the file is deleted, so your history still makes sense. It is yours: no
        other signed-in user can read it, and the database enforces that with row-level security
        rather than trusting the app alone.
      </p>

      <LegalHeading>Your account</LegalHeading>
      <p>
        Accounts are handled by Supabase Auth. Your email address and a hash of your password are
        stored there; the operator never sees the password itself. A profile row holds your email,
        an optional display name, your daily quota, and a flag recording what the sign-up checks
        thought of your email address (whether the domain is a known disposable one, and whether it
        can receive mail at all). You can use the app without an account, with a smaller daily
        allowance.
      </p>

      <LegalHeading>Activity events</LegalHeading>
      <p>
        The app records short events such as sign-up, sign-in, download started, download completed,
        download failed, and quota reached, so the operator can tell whether the app is working.
        Each event carries the event name, a few properties (for example the format and quality),
        your browser&apos;s user agent, and the time.
      </p>
      <p>
        Your IP address is never stored. What is stored is a salted hash of it, which cannot be
        turned back into the address, and which lets the operator recognise abuse from the same
        source without knowing where it is. These event rows are deleted after 90 days.
      </p>

      <LegalHeading>What is kept in your browser</LegalHeading>
      <ul>
        <li>
          A random id for this browser, so your downloads follow you around the app before you sign
          in. It is not linked to you personally and is claimed by your account if you sign in
          later.
        </li>
        <li>Your last format and quality choices, so the app opens where you left it.</li>
        <li>Whether you dismissed the install prompt.</li>
        <li>Your Supabase session, when you are signed in.</li>
      </ul>
      <p>Clearing your browser data removes all of it.</p>

      <LegalHeading>Other services involved</LegalHeading>
      <ul>
        <li>YouTube, which sees the server&apos;s request for the video, not yours.</li>
        <li>The hosting providers that run the app and its database.</li>
        <li>
          An error tracker, if the operator has switched one on. It receives the error itself, with
          request bodies, cookies, authentication headers, addresses, and pasted links stripped out
          before they leave the server.
        </li>
      </ul>
      <p>
        Whichever providers this instance uses are listed here by its operator:{" "}
        <Fill>HOSTING AND ANALYTICS PROVIDERS</Fill>.
      </p>

      <LegalHeading>Deleting everything</LegalHeading>
      <p>
        The Account page has a delete button. It removes your history rows, your stored files, your
        profile, and your login. It cannot be undone, and it is immediate. If you never made an
        account, clearing your browser data is the equivalent, and the rows you left behind expire
        with the events above.
      </p>

      <LegalHeading>Your rights</LegalHeading>
      <p>
        Depending on where you live you may have the right to see a copy of your data, correct it,
        or have it deleted. The delete button covers the last one; for the others, write to{" "}
        <Fill>CONTACT EMAIL</Fill>. If this instance serves people in a place with its own data
        protection rules, its operator should name the applicable law and their legal basis here:{" "}
        <Fill>APPLICABLE DATA PROTECTION LAW</Fill>.
      </p>
    </LegalPage>
  );
}
