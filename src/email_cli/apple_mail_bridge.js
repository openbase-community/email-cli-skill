// Apple Events bridge. JSON input stays on stdin, never in executable source or argv.
ObjC.import('Foundation');
function run() {
    const bytes = $.NSFileHandle.fileHandleWithStandardInput.readDataToEndOfFile;
    const p = JSON.parse(ObjC.unwrap($.NSString.alloc.initWithDataEncoding(bytes, $.NSUTF8StringEncoding)));
    const mail = Application('Mail');
    function accountInfo(a) {
        return {id: a.id(), name: a.name(), emails: a.emailAddresses(), enabled: a.enabled()};
    }
    if (p.action === 'accounts') return JSON.stringify({accounts: mail.accounts().map(accountInfo)});
    const matches = mail.accounts().filter(a => a.id() === p.account_id);
    if (matches.length !== 1) throw Error('Configured Apple Mail account is unavailable.');
    const account = matches[0];
    const emails = account.emailAddresses().map(s => s.toLowerCase());
    if (!account.enabled() || emails.indexOf(p.email.toLowerCase()) < 0)
        throw Error('Apple Mail account identity changed or account is disabled.');
    function folder(path) {
        let parent = account;
        path.forEach(name => {
            const found = parent.mailboxes().filter(b => b.name() === name);
            if (found.length !== 1) throw Error('Mailbox is missing or ambiguous; list folders again.');
            parent = found[0];
        });
        return parent;
    }
    function metadata(m) {
        return {local_id: m.id(), from: m.sender(), subject: m.subject(),
            received: m.dateReceived(), internet_message_id: m.messageId(), read: m.readStatus()};
    }
    function original() {
        const m = folder(p.folder).messages.byId(p.local_id);
        if (!m.exists() || m.messageId() !== p.internet_message_id)
            throw Error('Message moved, disappeared, or changed; search again.');
        return m;
    }
    function requireSender(m) {
        // Python validates the parsed address; compare the exact header again before body access.
        if (m.sender() !== p.expected_sender) throw Error('Message sender changed; access refused.');
    }
    if (p.action === 'folders') {
        const result = [];
        function visit(parent, path) {
            if (path.length > 30 || result.length > 5000) throw Error('Mailbox hierarchy too large.');
            parent.mailboxes().forEach(b => {
                const child = path.concat([b.name()]);
                result.push({path: child, name: b.name(), message_count: b.messages.length});
                visit(b, child);
            });
        }
        visit(account, []);
        return JSON.stringify({folders: result});
    }
    if (p.action === 'search') {
        const box = folder(p.folder), count = box.messages.length, result = [];
        let offset = p.offset, scanned = 0;
        while (offset < count && scanned < 250 && result.length < p.limit) {
            const m = box.messages[offset++];
            scanned++;
            const sender = m.sender().toLowerCase(), subject = m.subject().toLowerCase();
            if (p.terms.every(t => (t.field === 'from' ? sender :
                t.field === 'subject' ? subject : sender + '\n' + subject).indexOf(t.value) >= 0))
                result.push(metadata(m));
        }
        return JSON.stringify({messages: result, next_offset: offset < count ? offset : null,
            scanned: scanned, mailbox_message_count: count});
    }
    if (p.action === 'message') return JSON.stringify(metadata(original()));
    if (p.action === 'screening-source') {
        const m = original();
        requireSender(m);
        return JSON.stringify({source: m.source()});
    }
    if (p.action === 'body') {
        const m = original();
        requireSender(m);
        return JSON.stringify({body: m.content().slice(0, p.max_chars)});
    }
    function draftMetadata(d) {
        return {local_id: d.id(), sender: d.sender(), subject: d.subject(), body: d.content(),
            to: d.toRecipients().map(r => r.address()), cc: d.ccRecipients().map(r => r.address()),
            bcc: d.bccRecipients().map(r => r.address())};
    }
    if (p.action === 'draft-new' || p.action === 'draft-reply') {
        let d;
        if (p.action === 'draft-reply') {
            const m = original();
            requireSender(m);
            d = mail.reply(m, {openingWindow: false, replyToAll: p.reply_all});
            // Body is supplied by Python only after the approved-sender gate.
            d.content = p.body;
            d.sender = p.email;
        } else {
            d = mail.OutgoingMessage({subject: p.subject, content: p.body, sender: p.email,
                visible: false});
            mail.outgoingMessages.push(d);
            [['to', 'ToRecipient'], ['cc', 'CcRecipient'], ['bcc', 'BccRecipient']].forEach(pair => {
                p[pair[0]].forEach(r => d[pair[0] + 'Recipients'].push(mail[pair[1]]({address: r})));
            });
        }
        mail.save(d);
        return JSON.stringify(draftMetadata(d));
    }
    if (p.action === 'draft' || p.action === 'send') {
        const d = mail.outgoingMessages.byId(p.local_id);
        if (!d.exists()) throw Error('Compose draft is no longer open in Mail; do not recreate or resend automatically.');
        const current = draftMetadata(d);
        if (p.action === 'draft') return JSON.stringify(current);
        // Compare inside the same invocation immediately before sending.
        if (JSON.stringify(current) !== JSON.stringify(p.expected_draft))
            throw Error('Draft changed; sending refused.');
        return JSON.stringify({accepted: mail.send(d)});
    }
    throw Error('Unsupported Apple Mail bridge action.');
}
