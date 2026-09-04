import type { Metadata } from "next";

import { Fill, LegalHeading, LegalPage } from "@/components/legal";

export const metadata: Metadata = {
  title: "Terms of Service · Downloader Manager",
  description: "What this app is, what it is not, and the rules for using it.",
};

export default function TermsPage() {
  return (
    <LegalPage
      title="Terms of Service"
      intro="Plain English, because these actually have to be read."
    >
      <LegalHeading>What this is</LegalHeading>
      <p>
        Downloader Manager is a small personal tool, run by <Fill>OPERATOR NAME</Fill>, that takes a
        YouTube link and gives back an audio or video file. It is offered to the people the operator
        chose to share it with. It is not a public service, it is not a business, nothing is sold,
        and there is no advertising.
      </p>
      <p>
        There is no uptime promise. The app may be slow, may be switched off, and may stop working
        entirely the next time YouTube changes something. Daily download limits apply and can be
        changed at any time to keep the running costs near zero.
      </p>

      <LegalHeading>Personal use only</LegalHeading>
      <p>By using this app you confirm that:</p>
      <ul>
        <li>
          you are downloading content you own, content published under a licence that allows it, or
          content you have the copyright holder&apos;s permission to download;
        </li>
        <li>the file is for your own personal, non-commercial use;</li>
        <li>
          you will not republish, sell, or redistribute what you download, and will not use it to
          build another service;
        </li>
        <li>you are responsible for what you download, and for the law that applies to you.</li>
      </ul>

      <LegalHeading>YouTube&apos;s own terms</LegalHeading>
      <p>
        YouTube&apos;s Terms of Service prohibit downloading content except where YouTube provides a
        download button or the law expressly allows it. Using this app may therefore break your
        agreement with YouTube even where it breaks no copyright law. That is your decision to make,
        not the operator&apos;s, and this app does not grant you any right you did not already have.
        Some countries allow a private copy of material you have lawfully accessed; many do not.
        Check what applies where you are: <Fill>JURISDICTION</Fill>.
      </p>

      <LegalHeading>What you may not do</LegalHeading>
      <ul>
        <li>Download content you have no right to download.</li>
        <li>Use the app to distribute copyrighted material to other people.</li>
        <li>
          Work around the daily limits with scripts, multiple accounts, or repeated anonymous
          identities.
        </li>
        <li>Attack, overload, or probe the server, or try to reach other people&apos;s files.</li>
      </ul>
      <p>
        Accounts and network addresses that break these rules can be blocked without warning. Where
        the operator can tell you why, they will.
      </p>

      <LegalHeading>Your account and your files</LegalHeading>
      <p>
        A finished file is kept in a folder on the machine running this app until someone deletes
        it. Nothing expires on a timer, so nothing disappears from under you - and equally, nothing
        tidies up after you: every download in your history has a delete button that removes the
        file and the entry together, and deleting your account removes the lot. The operator may
        set a retention period on a shared server, in which case the app shows the deadline on the
        download itself.
      </p>
      <p>
        Disk space, like everything else here, is finite and is the operator&apos;s to manage. They
        may delete files, refuse new downloads, or change the limits when it runs short. Keep your
        own copy of anything you care about: this app is a tool, not a backup.
      </p>

      <LegalHeading>No warranty, no liability</LegalHeading>
      <p>
        The app is provided as it is, with no warranty of any kind. To the extent the law allows,
        the operator is not liable for any loss arising from using it, including lost files, lost
        time, or any claim brought against you over what you chose to download.
      </p>

      <LegalHeading>Changes and contact</LegalHeading>
      <p>
        These terms may change; the date at the top says when they last did. Questions go to{" "}
        <Fill>CONTACT EMAIL</Fill>. Copyright complaints have their own page:{" "}
        <a href="/dmca">Copyright and contact</a>.
      </p>
    </LegalPage>
  );
}
