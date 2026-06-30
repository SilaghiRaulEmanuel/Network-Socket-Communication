const net = require('net');
const readline = require('readline');
const dgram = require('dgram');

const SERVER_HOST = "127.0.0.1";
const SERVER_PORT = 9009;
const UDP_PORT = 9010;

const rl = readline.createInterface({ input: process.stdin, output: process.stdout });

rl.question("Nume jucator: ", (nameInput) => {
    const name = nameInput.trim() || "Anonim";
    const client = new net.Socket();

    let buffer = "";
    let currentQuestion = null;
    let buzzed = false;

    function askAnswer() {
        if (!currentQuestion) return;

        rl.question("Alege (1-4) sau b pentru buzz: ", (inputRaw) => {
            const input = inputRaw.trim().toLowerCase();

            if (input === 'b') {
                if (!buzzed) {
                    // trimite buzz UDP
                    const u = dgram.createSocket('udp4');
                    u.send(Buffer.from('BUZZ:' + name), 0, '255.255.255.255', UDP_PORT, () => u.close());
                    buzzed = true;
                    console.log("BUZZ trimis! Acum poți răspunde.");
                } else {
                    console.log("Ai deja buzz-uit! Poți răspunde acum.");
                }
                askAnswer(); // prompt continuă pentru a permite să răspundă numeric
            } else if (["1", "2", "3", "4"].includes(input)) {
                const idx = parseInt(input) - 1;
                client.write(JSON.stringify({ type: 'ANSWER', id: currentQuestion.id, answer: currentQuestion.choices[idx] }) + "\n");

                // reset pentru următoarea întrebare
                buzzed = false;
                currentQuestion = null;
            } else {
                console.log("Răspuns invalid. Folosește 1-4 sau b.");
                askAnswer();
            }
        });
    }

    client.connect(SERVER_PORT, SERVER_HOST, () => {
        console.log(`Conectat la server ${SERVER_HOST}:${SERVER_PORT}`);
        client.write(JSON.stringify({ name: name }) + "\n");
    });

    client.on("data", (data) => {
        buffer += data.toString();
        while (buffer.includes("\n")) {
            const idx = buffer.indexOf("\n");
            const line = buffer.slice(0, idx);
            buffer = buffer.slice(idx + 1);
            if (!line.trim()) continue;
            try {
                const msg = JSON.parse(line);

                if (msg.type === "QUESTION") {
                    console.log("\nIntrebare:", msg.text);
                    msg.choices.forEach((c, i) => console.log(`${i + 1}) ${c}`));
                    currentQuestion = msg;
                    buzzed = false;
                    askAnswer();
                }
                else if (msg.type === "INFO") {
                    console.log("[INFO]", msg.msg);
                }
                else if (msg.type === "SCORES") {
                    console.log("Scoruri:", msg.scores);
                }
            } catch (e) {}
        }
    });

    client.on("close", () => { console.log("Conexiune închisă de server."); process.exit(0); });
    client.on("error", (err) => { console.log("Eroare:", err.message); process.exit(1); });
});
