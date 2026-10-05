import DocPage from '../components/doc-page';
import { docMetadata, loadDoc } from '../../lib/docs';

const doc = loadDoc('cookbook');

export const metadata = docMetadata(doc);

export default function Cookbook() {
  return <DocPage doc={doc} />;
}
