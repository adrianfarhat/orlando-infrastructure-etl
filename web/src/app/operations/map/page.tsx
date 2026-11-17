import OperationsView from "@/components/OperationsView";
import styles from "./operations.module.css";

export default function OperationsMapPage() {
  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <h1>Orlando Infrastructure Explorer</h1>
        <p>City Operations | Infrastructure Map</p>
      </header>

      <OperationsView />
    </main>
  );
}
