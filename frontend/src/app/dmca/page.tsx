import type { Metadata } from "next";

import { Fill, LegalHeading, LegalPage } from "@/components/legal";

export const metadata: Metadata = {
  title: "Copyright and contact · Downloader Manager",
  description: "How to reach the operator, and how to send a copyright complaint.",
};

export default function DmcaPage() {
  return (
    <LegalPage
      title="Copyright and contact"
      intro="How to reach the person running this, including about copyright."
    >
      <LegalHeading>Contact</LegalHeading>
      <p>
        This instance is run by <Fill>OPERATOR NAME</Fill>, in <Fill>COUNTRY</Fill>. Everything,
        including copyright complaints, goes to <Fill>CONTACT EMAIL</Fill>. Postal address, if one
        is required where the operator lives: <Fill>POSTAL ADDRESS</Fill>.
      </p>

      <LegalHeading>What this app does with content</LegalHeading>
      <p>
        Nothing is uploaded here and nothing is published here. When someone pastes a link, the
        server fetches that video from YouTube, converts it, and hands the file to the person who
        asked. A copy stays in a private folder on that machine, reachable only by the person who
        downloaded it, until they delete it. There is no library, no search, no public index, no
        sharing between users, and no way to browse what anyone else downloaded. The app cannot
        make private content public: it can only reach what YouTube already serves.
      </p>
      <p>
        So the usual takedown target does not exist: there is no page to remove. What the operator
        can do is block a specific video, block a user, or shut the app down, and they will act on a
        good-faith complaint.
      </p>

      <LegalHeading>Sending a copyright complaint</LegalHeading>
      <p>
        Email <Fill>CONTACT EMAIL</Fill> with the subject &ldquo;Copyright complaint&rdquo; and
        include, in the form the DMCA asks for (17 U.S.C. §512(c)(3)) even if you are not in the
        United States, since it is a good checklist either way:
      </p>
      <ul>
        <li>your name, address, telephone number, and email address;</li>
        <li>
          identification of the copyrighted work, or a representative list if there are several;
        </li>
        <li>
          the YouTube link or video id you say is being infringed through this app, precisely enough
          to be blocked;
        </li>
        <li>
          a statement that you believe in good faith that the use is not authorised by the copyright
          owner, its agent, or the law;
        </li>
        <li>
          a statement that the information in your notice is accurate and, under penalty of perjury,
          that you are the copyright owner or authorised to act for them;
        </li>
        <li>your physical or electronic signature.</li>
      </ul>
      <p>
        Expect a reply within <Fill>NUMBER</Fill> business days. A valid complaint results in that
        video being refused by this app, and in the account responsible being blocked where one is
        involved.
      </p>

      <LegalHeading>If you think a block was wrong</LegalHeading>
      <p>
        Write to the same address with the material that was blocked, why you believe the complaint
        was mistaken, and how to reach you. Because nothing is hosted or published here, this is a
        conversation with the operator rather than a formal counter-notice process.
      </p>

      <LegalHeading>Repeat infringers</LegalHeading>
      <p>
        Accounts that attract repeated valid complaints are blocked permanently, and their history
        and files are deleted. The block list is checked before any download starts.
      </p>

      <LegalHeading>Designated agent</LegalHeading>
      <p>
        A formal DMCA safe harbour requires an agent registered with the U.S. Copyright Office. This
        app is a personal tool rather than a public service, so its operator may well not have one.
        If this instance does, its details belong here: <Fill>DESIGNATED AGENT DETAILS</Fill>.
      </p>
    </LegalPage>
  );
}
