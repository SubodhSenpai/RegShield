import DocPage from '../components/doc-page';
import { docMetadata, loadDoc } from '../../lib/docs';

const doc = loadDoc('getting-started');

export const metadata = docMetadata(doc);

export default function GettingStarted() {
  return <DocPage doc={doc} />;
}
