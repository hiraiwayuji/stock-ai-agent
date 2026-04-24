from pathlib import Path
import streamlit as st

st.set_page_config(page_title="📖 マニュアル — 株ボールシステム", page_icon="📖", layout="wide")

MANUAL_PATH = Path(__file__).parent.parent / "docs" / "manual.md"


def main():
    if not MANUAL_PATH.exists():
        st.error(f"マニュアルファイルが見つかりません: {MANUAL_PATH}")
        return
    
    content = MANUAL_PATH.read_text(encoding="utf-8")
    st.markdown(content)
    
    st.markdown("---")
    st.caption("このマニュアルは docs/manual.md を編集して更新できます。")


if __name__ == "__main__":
    main()
