SECRET_TOKEN = "";

function res_json(obj) {
    return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

function doGet(e) {
    if (e.parameter.token === SECRET_TOKEN) {
        return res_json({ status: "ok" });
    }

    return res_json({ status: "forbidden" });
}

function doPost(e) {
    try {
        if (e.postData.type === "application/json") {
            if (e.parameter.token === SECRET_TOKEN) {
                const data = JSON.parse(e.postData.contents);
                if (Array.isArray(data) && data.every(item => (
                    typeof item.time === "string" &&
                    typeof item.mentee_std_id === "number" &&
                    typeof item.mentee_name === "string" &&
                    typeof item.mentor_std_id === "number" &&
                    typeof item.mentor_name === "string" &&
                    typeof item.message === "string"
                ))) {
                    const sheet = SpreadsheetApp.getActiveSheet();
                    data.forEach((item) => {
                        sheet.appendRow([item.time, item.mentee_std_id, item.mentee_name, item.mentor_std_id, item.mentor_name, item.message]);
                    });

                    return res_json({ status: "ok" });
                }

                return res_json({ status: "bad_request" });
            }

            return res_json({ status: "forbidden" });
        }
    } catch (error) {
        return res_json({ status: "bad_request" });
    }
}
