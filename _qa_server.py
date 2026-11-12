
import os, tempfile
os.environ["WING_DATA_DIR"] = tempfile.mkdtemp()
import app as A
A.app.config["WING_LOGIN_REQUIRED"] = False
A.sync.run_once()
# 주력 상품 3개 지정 (그리드가 여러 줄 되는지도 본다)
for it in A.store.items()[:3]:
    A.store.update_rule(it["vendor_item_id"], featured=1)
print("FEATURED:", [i["vendor_item_id"] for i in A.store.items() if i["featured"]])
A.app.run(host="127.0.0.1", port=26500, debug=False, use_reloader=False)
